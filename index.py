from __future__ import annotations

import hashlib
import io
import json
import secrets
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, make_response, request, send_from_directory

from app import service
from app.database import db, password_is_configured, set_password, verify_password, verify_recovery
from app.exports import export_csv, export_pdf, export_xlsx


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
SESSION_TTL_DAYS = 30
app = Flask(__name__, static_folder=None)


def body():
    if request.content_length and request.content_length > 2_000_000:
        raise ValueError("Données trop volumineuses.")
    return request.get_json(silent=True) or {}


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticated():
    token = request.cookies.get("dadou_session", "")
    if not token:
        return False
    with db() as conn:
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE token_hash=? AND expires_at>now()",
            (token_hash(token),),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE sessions SET expires_at=now()+(? || ' days')::interval WHERE token_hash=?",
                (str(SESSION_TTL_DAYS), token_hash(token)),
            )
    return bool(row)


def require_auth():
    if not authenticated():
        return jsonify({"error": "Session expirée. Veuillez vous reconnecter."}), 401
    return None


def login_response(recovery=None):
    token = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute(
            "INSERT INTO sessions(token_hash,expires_at,created_at) VALUES(?,now()+(? || ' days')::interval,now())",
            (token_hash(token), str(SESSION_TTL_DAYS)),
        )
    payload = {"ok": True}
    if recovery:
        payload["recovery"] = recovery
    response = make_response(jsonify(payload))
    response.set_cookie(
        "dadou_session",
        token,
        max_age=SESSION_TTL_DAYS * 86400,
        secure=True,
        httponly=True,
        samesite="Strict",
        path="/",
    )
    return response


@app.after_request
def security_headers(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.route("/")
def home():
    return send_from_directory(PUBLIC, "index.html")


@app.route("/<path:name>")
def public_file(name):
    candidate = (PUBLIC / name).resolve()
    if PUBLIC.resolve() not in candidate.parents:
        return "Accès refusé", 403
    if candidate.is_file():
        return send_from_directory(PUBLIC, name)
    return send_from_directory(PUBLIC, "index.html")


@app.get("/health")
def health():
    try:
        with db() as conn:
            conn.execute("SELECT 1").fetchone()
        database = "ready"
    except Exception:
        database = "unavailable"
    return jsonify({"application": "La boutique à Dadou", "database": database, "release": 1})


@app.route("/api/auth/state")
def auth_state():
    return jsonify({"configured": password_is_configured(), "authenticated": authenticated()})


@app.post("/api/auth/setup")
def auth_setup():
    if password_is_configured():
        return jsonify({"error": "Le compte est déjà configuré."}), 409
    return login_response(set_password(str(body().get("password", ""))))


@app.post("/api/auth/login")
def auth_login():
    if not verify_password(str(body().get("password", ""))):
        return jsonify({"error": "Mot de passe incorrect."}), 401
    return login_response()


@app.post("/api/auth/recover")
def auth_recover():
    payload = body()
    if not verify_recovery(str(payload.get("recovery", ""))):
        return jsonify({"error": "Code de récupération incorrect."}), 401
    return login_response(set_password(str(payload.get("password", ""))))


@app.post("/api/auth/logout")
def auth_logout():
    token = request.cookies.get("dadou_session", "")
    if token:
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
    response = make_response(jsonify({"ok": True}))
    response.delete_cookie("dadou_session", path="/")
    return response


@app.route("/api/<path:path>", methods=["GET", "POST", "DELETE"])
def api_route(path):
    denied = require_auth()
    if denied:
        return denied
    try:
        if request.method == "GET":
            return api_get(path)
        if request.method == "POST":
            return api_post(path)
        if request.method == "DELETE":
            parts = path.split("/")
            if len(parts) == 2 and parts[0] == "items":
                service.archive_item(int(parts[1]))
                return jsonify({"ok": True})
        return jsonify({"error": "Route inconnue."}), 404
    except (ValueError, KeyError) as exc:
        return jsonify({"error": str(exc).strip("'\"")}), 400
    except Exception:
        app.logger.exception("API failure")
        return jsonify({"error": "Une erreur inattendue est survenue."}), 500


def api_get(path):
    one = lambda key, default="": request.args.get(key, default)
    if path == "categories":
        return jsonify(service.get_categories())
    if path == "items":
        return jsonify(service.list_items(one("search"), one("status"), one("category")))
    if path.startswith("items/") and path.endswith("/sales"):
        return jsonify(service.list_item_sales(int(path.split("/")[1])))
    if path.startswith("items/"):
        return jsonify(service.get_item(int(path.split("/")[1])))
    if path == "dashboard":
        return jsonify(service.dashboard(one("year") or None, one("month") or None))
    if path == "top-sales":
        return jsonify(service.top_sales(one("period", "all"), one("category"), one("platform")))
    if path == "watchlist":
        return jsonify(service.list_watchlist())
    if path == "accounting":
        return jsonify(service.accounting(one("start"), one("end"), one("platform"), one("kind", "all")))
    if path.startswith("export/"):
        ext = path.split("/")[-1]
        data = service.accounting(one("start"), one("end"), one("platform"), one("kind", "all"))
        title = f"Livre de compte · du {one('start')} au {one('end')}"
        content = export_csv(data) if ext == "csv" else export_pdf(data, title) if ext == "pdf" else export_xlsx(data, title)
        mime = {"csv": "text/csv; charset=utf-8", "pdf": "application/pdf",
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}[ext]
        filename = f"La_boutique_a_Dadou_{one('start')}_{one('end')}.{ext}"
        return Response(content, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    if path == "backup":
        return database_backup()
    if path == "telegram/status":
        return jsonify({"configured": False, "paired": False, "running": False,
                        "last_error": "Telegram reste disponible uniquement dans la version locale."})
    return jsonify({"error": "Route inconnue."}), 404


def api_post(path):
    payload = body()
    if path == "categories":
        return jsonify(service.add_category(payload)), 201
    if path == "items":
        return jsonify(service.save_item(payload)), 201
    if path == "batches":
        return jsonify(service.create_batch(payload)), 201
    if path == "watchlist":
        return jsonify(service.upsert_watch(payload))
    if path.startswith("telegram/"):
        raise ValueError("La configuration Telegram reste liée au logiciel local.")
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == "items":
        item_id = int(parts[1])
        if len(parts) == 2:
            return jsonify(service.save_item(payload, item_id))
        action = parts[2]
        if action == "sell":
            return jsonify(service.sell_item(item_id, payload))
        if action == "cancel-sale":
            return jsonify(service.cancel_sale(item_id))
        if action == "finalize-sale":
            return jsonify(service.finalize_sale(item_id))
        if action == "status":
            return jsonify(service.change_status(item_id, payload.get("status")))
    return jsonify({"error": "Route inconnue."}), 404


def database_backup():
    table_names = ["settings", "categories", "products", "purchase_batches", "items",
                   "sales", "watchlist", "activity_log"]
    stream = io.BytesIO()
    with db() as conn, zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for table in table_names:
            rows = [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()]
            archive.writestr(f"{table}.json", json.dumps(rows, ensure_ascii=False, default=str, indent=2))
        archive.writestr("LISEZ-MOI.txt", "Sauvegarde de La boutique à Dadou en ligne.\n")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Response(stream.getvalue(), mimetype="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="Dadou_sauvegarde_{stamp}.zip"'})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8878, debug=False)
