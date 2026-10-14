from __future__ import annotations

import json
from datetime import date

from .database import db, money, next_code, now_iso, row_dict, safe_date


ITEM_SELECT = """
SELECT i.*, p.name AS product_name, p.category_id AS category_id,
       c.name AS category_name, c.color AS category_color,
       s.id AS sale_id, s.sale_price, s.platform, s.sale_date, s.transaction_ref,
       s.finalized_at, s.quantity AS sale_quantity, s.cost_basis,
       CASE WHEN s.id IS NULL THEN NULL ELSE ROUND(s.sale_price-s.cost_basis,2) END AS margin,
       CASE WHEN s.id IS NULL OR s.cost_basis=0 THEN NULL
            ELSE ROUND((s.sale_price-s.cost_basis)*100.0/s.cost_basis,1) END AS margin_rate,
       CASE WHEN s.id IS NULL THEN NULL ELSE (s.sale_date::date-i.listed_date::date) END AS sale_days,
       ROUND(i.purchase_price*1.0/i.initial_quantity,2) AS unit_cost,
       COALESCE((SELECT SUM(sx.quantity) FROM sales sx WHERE sx.item_id=i.id AND sx.cancelled_at IS NULL AND sx.finalized_at IS NOT NULL),0) AS sold_quantity,
       COALESCE((SELECT SUM(sx.quantity) FROM sales sx WHERE sx.item_id=i.id AND sx.cancelled_at IS NULL AND sx.finalized_at IS NULL),0) AS pending_quantity,
       i.initial_quantity-COALESCE((SELECT SUM(sx.quantity) FROM sales sx WHERE sx.item_id=i.id AND sx.cancelled_at IS NULL),0) AS available_quantity,
       (SELECT COUNT(*) FROM sales sx WHERE sx.item_id=i.id AND sx.cancelled_at IS NULL AND sx.finalized_at IS NOT NULL) AS sale_count,
       CASE WHEN w.id IS NULL THEN 0 ELSE 1 END AS watched
FROM items i
JOIN products p ON p.id=i.product_id
LEFT JOIN categories c ON c.id=p.category_id
LEFT JOIN sales s ON s.id=(
    SELECT sx.id FROM sales sx WHERE sx.item_id=i.id AND sx.cancelled_at IS NULL
    ORDER BY CASE WHEN sx.finalized_at IS NULL THEN 0 ELSE 1 END, sx.id DESC LIMIT 1
)
LEFT JOIN watchlist w ON w.product_id=p.id AND w.active=1
"""


def get_categories():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM categories ORDER BY name")]


def add_category(payload):
    name = str(payload.get("name", "")).strip()
    color = str(payload.get("color", "#B7793E"))
    if not name:
        raise ValueError("Le nom de la catégorie est obligatoire.")
    with db() as conn:
        row = conn.execute(
            "INSERT INTO categories(name,color,created_at) VALUES(?,?,?) RETURNING id",
            (name, color, now_iso()),
        ).fetchone()
        return row_dict(conn.execute("SELECT * FROM categories WHERE id=?", (row[0],)).fetchone())


def _get_or_create_product(conn, name, category_id):
    name = name.strip()
    row = conn.execute(
        "SELECT id FROM products WHERE name=? AND category_id IS NOT DISTINCT FROM ?", (name, category_id)
    ).fetchone()
    if row:
        return row["id"]
    return conn.execute(
        "INSERT INTO products(name,category_id,created_at) VALUES(?,?,?) RETURNING id",
        (name, category_id, now_iso()),
    ).fetchone()[0]


def list_items(search="", status="", category=""):
    clauses = ["i.archived=0"]
    args = []
    if search:
        clauses.append("(i.designation ILIKE ? OR i.serial_number ILIKE ? OR i.notes ILIKE ? OR i.code ILIKE ? OR p.name ILIKE ? OR COALESCE(s.transaction_ref,'') ILIKE ?)")
        term = f"%{search.strip()}%"
        args.extend([term] * 6)
    if status == "vente_en_cours":
        clauses.append("s.id IS NOT NULL AND s.finalized_at IS NULL")
    elif status == "vente_finalisee":
        clauses.append("i.status='vendu' AND s.finalized_at IS NOT NULL")
    elif status:
        clauses.append("i.status=?")
        args.append(status)
    if category:
        clauses.append("c.id=?")
        args.append(category)
    sql = ITEM_SELECT + " WHERE " + " AND ".join(clauses) + " ORDER BY i.updated_at DESC"
    with db() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def get_item(item_id):
    with db() as conn:
        row = conn.execute(ITEM_SELECT + " WHERE i.id=?", (item_id,)).fetchone()
        if not row:
            raise KeyError("Article introuvable.")
        return dict(row)


def get_item_by_code(code):
    normalized = str(code).strip().upper()
    with db() as conn:
        row = conn.execute(ITEM_SELECT + " WHERE UPPER(i.code)=? AND i.archived=0", (normalized,)).fetchone()
        if not row:
            raise KeyError("Article introuvable.")
        return dict(row)


def list_item_sales(item_id):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone():
            raise KeyError("Article introuvable.")
        rows = conn.execute(
            """SELECT id,sale_price,platform,sale_date,transaction_ref,quantity,cost_basis,
               ROUND(sale_price-cost_basis,2) margin,finalized_at,cancelled_at,created_at
               FROM sales WHERE item_id=? ORDER BY sale_date DESC,id DESC""", (item_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def save_item(payload, item_id=None):
    designation = str(payload.get("designation", "")).strip()
    if not designation:
        raise ValueError("La désignation est obligatoire.")
    product_name = str(payload.get("product_name") or designation).strip()
    category_id = payload.get("category_id") or None
    purchase_date = safe_date(str(payload.get("purchase_date", "")), "achat")
    listed_date = safe_date(str(payload.get("listed_date", "")), "mise en ligne")
    purchase_price = money(payload.get("purchase_price"), "prix d’achat")
    list_price = money(payload.get("list_price") or 0, "prix affiché")
    serial = str(payload.get("serial_number", "")).strip()
    notes = str(payload.get("notes", "")).strip()
    status = str(payload.get("status") or "")
    inventory_mode = str(payload.get("inventory_mode") or "single")
    if inventory_mode not in {"single", "quantity"}:
        raise ValueError("Le type de stock est invalide.")
    try:
        initial_quantity = int(payload.get("initial_quantity") or 1)
    except Exception as exc:
        raise ValueError("La quantité initiale est invalide.") from exc
    if initial_quantity < 1:
        raise ValueError("La quantité initiale doit être supérieure à zéro.")
    if inventory_mode == "single":
        initial_quantity = 1
    with db() as conn:
        product_id = _get_or_create_product(conn, product_name, category_id)
        stamp = now_iso()
        if item_id:
            found = conn.execute("SELECT id,status,inventory_mode,initial_quantity FROM items WHERE id=?", (item_id,)).fetchone()
            if not found:
                raise KeyError("Article introuvable.")
            if not status:
                status = found["status"]
            if status not in {"en_vente", "reserve", "vendu", "retire"}:
                status = found["status"]
            inventory_mode = found["inventory_mode"]
            initial_quantity = found["initial_quantity"]
            conn.execute(
                """UPDATE items SET product_id=?,designation=?,serial_number=?,purchase_price=?,
                   list_price=?,purchase_date=?,listed_date=?,notes=?,status=?,updated_at=? WHERE id=?""",
                (product_id, designation, serial, purchase_price, list_price, purchase_date,
                 listed_date, notes, status, stamp, item_id),
            )
        else:
            status = "en_vente"
            code = next_code(conn)
            row = conn.execute(
                """INSERT INTO items(code,product_id,designation,serial_number,purchase_price,
                   list_price,purchase_date,listed_date,status,notes,inventory_mode,initial_quantity,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (code, product_id, designation, serial, purchase_price, list_price,
                 purchase_date, listed_date, "en_vente", notes, inventory_mode, initial_quantity, stamp, stamp),
            )
            item_id = row.fetchone()[0]
            conn.execute(
                "INSERT INTO activity_log(kind,label,item_id,amount,occurred_on,created_at) VALUES(?,?,?,?,?,?)",
                ("achat", f"Achat · {designation}", item_id, purchase_price, purchase_date, stamp),
            )
    return get_item(item_id)


def create_batch(payload):
    entries = payload.get("items") or []
    if not isinstance(entries, list) or not entries:
        raise ValueError("Ajoutez au moins un article au lot.")
    total_price = money(payload.get("total_price"), "prix global du lot")
    purchase_date = safe_date(str(payload.get("purchase_date", "")), "achat")
    listed_date = safe_date(str(payload.get("listed_date", "")), "mise en ligne")
    name = str(payload.get("name") or f"Lot du {purchase_date}").strip()
    cents = int(round(total_price * 100))
    base, remainder = divmod(cents, len(entries))
    created_ids = []
    with db() as conn:
        stamp = now_iso()
        batch_id = conn.execute(
            "INSERT INTO purchase_batches(name,total_price,item_count,purchase_date,created_at) VALUES(?,?,?,?,?) RETURNING id",
            (name, total_price, len(entries), purchase_date, stamp),
        ).fetchone()[0]
        for index, entry in enumerate(entries):
            designation = str(entry.get("designation", "")).strip()
            if not designation:
                raise ValueError(f"La désignation de l’article {index + 1} est obligatoire.")
            category_id = entry.get("category_id") or payload.get("category_id") or None
            if not category_id:
                raise ValueError(f"La catégorie de l’article {index + 1} est obligatoire.")
            allocated = (base + (1 if index < remainder else 0)) / 100
            list_price = money(entry.get("list_price") or 0, "prix affiché")
            product_id = _get_or_create_product(conn, designation, category_id)
            code = next_code(conn)
            item_id = conn.execute(
                """INSERT INTO items(code,product_id,batch_id,designation,serial_number,purchase_price,
                   list_price,purchase_date,listed_date,status,notes,inventory_mode,initial_quantity,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,'en_vente',?,'single',1,?,?) RETURNING id""",
                (code, product_id, batch_id, designation, str(entry.get("serial_number", "")).strip(),
                 allocated, list_price, purchase_date, listed_date, str(entry.get("notes", "")).strip(), stamp, stamp),
            ).fetchone()[0]
            created_ids.append(item_id)
            conn.execute(
                "INSERT INTO activity_log(kind,label,item_id,amount,occurred_on,created_at) VALUES(?,?,?,?,?,?)",
                ("achat", f"Achat lot · {designation}", item_id, allocated, purchase_date, stamp),
            )
    return {"batch_id": batch_id, "item_count": len(created_ids), "total_price": total_price,
            "items": [get_item(item_id) for item_id in created_ids]}


def change_status(item_id, status):
    if status not in {"en_vente", "reserve", "retire"}:
        raise ValueError("Ce changement de statut n’est pas autorisé.")
    with db() as conn:
        exists = conn.execute("SELECT id FROM items WHERE id=?", (item_id,)).fetchone()
        if not exists:
            raise KeyError("Article introuvable.")
        conn.execute("UPDATE items SET status=?,updated_at=? WHERE id=?", (status, now_iso(), item_id))
    return get_item(item_id)


def sell_item(item_id, payload):
    price = money(payload.get("sale_price"), "prix de vente")
    platform = str(payload.get("platform", ""))
    if platform not in {"Vinted", "Leboncoin", "eBay", "Autre"}:
        raise ValueError("Veuillez sélectionner une plateforme.")
    sale_date = safe_date(str(payload.get("sale_date", "")), "vente")
    ref = str(payload.get("transaction_ref", "")).strip()
    try:
        quantity = int(payload.get("quantity") or 1)
    except Exception as exc:
        raise ValueError("La quantité vendue est invalide.") from exc
    if quantity < 1:
        raise ValueError("La quantité vendue doit être supérieure à zéro.")
    with db() as conn:
        item = conn.execute(
            "SELECT designation,status,inventory_mode,initial_quantity,purchase_price FROM items WHERE id=?",
            (item_id,),
        ).fetchone()
        if not item:
            raise KeyError("Article introuvable.")
        if conn.execute(
            "SELECT 1 FROM sales WHERE item_id=? AND cancelled_at IS NULL AND finalized_at IS NULL", (item_id,)
        ).fetchone():
            raise ValueError("Cet article possède déjà une vente en cours.")
        reserved = conn.execute(
            "SELECT COALESCE(SUM(quantity),0),COALESCE(SUM(cost_basis),0) FROM sales WHERE item_id=? AND cancelled_at IS NULL",
            (item_id,),
        ).fetchone()
        available = item["initial_quantity"] - reserved[0]
        if item["inventory_mode"] == "single":
            quantity = 1
        if quantity > available:
            raise ValueError(f"Il ne reste que {available} unité(s) disponible(s).")
        if quantity == available:
            cost_basis = round(item["purchase_price"] - reserved[1], 2)
        else:
            cost_basis = round(item["purchase_price"] * quantity / item["initial_quantity"], 2)
        stamp = now_iso()
        conn.execute(
            """INSERT INTO sales(item_id,sale_price,platform,sale_date,transaction_ref,quantity,cost_basis,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (item_id, price, platform, sale_date, ref, quantity, cost_basis, stamp),
        )
        if item["inventory_mode"] == "single":
            conn.execute("UPDATE items SET status='vendu',updated_at=? WHERE id=?", (stamp, item_id))
        else:
            conn.execute("UPDATE items SET updated_at=? WHERE id=?", (stamp, item_id))
        qty_label = f" · {quantity} unité(s)" if item["inventory_mode"] == "quantity" else ""
        conn.execute(
            "INSERT INTO activity_log(kind,label,item_id,amount,occurred_on,created_at) VALUES(?,?,?,?,?,?)",
            ("vente_en_cours", f"Vente en cours {platform} · {item['designation']}{qty_label}", item_id, price, sale_date, stamp),
        )
    return get_item(item_id)


def finalize_sale(item_id):
    with db() as conn:
        sale = conn.execute(
            """SELECT s.id,s.sale_price,s.sale_date,s.platform,s.quantity,i.designation,
                      i.inventory_mode,i.initial_quantity
               FROM sales s JOIN items i ON i.id=s.item_id
               WHERE s.item_id=? AND s.cancelled_at IS NULL AND s.finalized_at IS NULL""", (item_id,)
        ).fetchone()
        if not sale:
            raise ValueError("Aucune vente en cours à finaliser.")
        stamp = now_iso()
        conn.execute("UPDATE sales SET finalized_at=? WHERE id=?", (stamp, sale["id"]))
        used = conn.execute(
            "SELECT COALESCE(SUM(quantity),0) FROM sales WHERE item_id=? AND cancelled_at IS NULL", (item_id,)
        ).fetchone()[0]
        new_status = "vendu" if used >= sale["initial_quantity"] else "en_vente"
        conn.execute("UPDATE items SET status=?,updated_at=? WHERE id=?", (new_status, stamp, item_id))
        qty_label = f" · {sale['quantity']} unité(s)" if sale["inventory_mode"] == "quantity" else ""
        conn.execute(
            "INSERT INTO activity_log(kind,label,item_id,amount,occurred_on,created_at) VALUES(?,?,?,?,?,?)",
            ("vente", f"Vente finalisée {sale['platform']} · {sale['designation']}{qty_label}",
             item_id, sale["sale_price"], sale["sale_date"], stamp),
        )
    return get_item(item_id)


def cancel_sale(item_id):
    with db() as conn:
        sale = conn.execute(
            "SELECT id FROM sales WHERE item_id=? AND cancelled_at IS NULL AND finalized_at IS NULL", (item_id,)
        ).fetchone()
        if not sale:
            raise ValueError("Aucune vente active à annuler.")
        stamp = now_iso()
        conn.execute("UPDATE sales SET cancelled_at=? WHERE id=?", (stamp, sale["id"]))
        conn.execute("UPDATE items SET status='en_vente',updated_at=? WHERE id=?", (stamp, item_id))
    return get_item(item_id)


def archive_item(item_id):
    with db() as conn:
        conn.execute("UPDATE items SET archived=1,updated_at=? WHERE id=?", (now_iso(), item_id))


def dashboard(year=None, month=None):
    year = int(year or date.today().year)
    month = int(month or date.today().month)
    month_prefix = f"{year:04d}-{month:02d}"
    year_prefix = f"{year:04d}"
    with db() as conn:
        def period_metrics(prefix):
            purchases = conn.execute(
                """SELECT COALESCE(SUM(purchase_price),0),
                   COUNT(DISTINCT CASE WHEN batch_id IS NULL THEN 'I'||id ELSE 'B'||batch_id END)
                   FROM items WHERE archived=0 AND purchase_date LIKE ?""",
                (prefix + "%",),
            ).fetchone()
            sales = conn.execute(
                """SELECT COALESCE(SUM(s.sale_price),0), COALESCE(SUM(s.cost_basis),0), COALESCE(SUM(s.quantity),0)
                   FROM sales s JOIN items i ON i.id=s.item_id
                   WHERE s.cancelled_at IS NULL AND s.finalized_at IS NOT NULL AND i.archived=0 AND s.sale_date LIKE ?""",
                (prefix + "%",),
            ).fetchone()
            return {
                "spent": round(purchases[0], 2), "purchased_count": purchases[1],
                "revenue": round(sales[0], 2), "sold_cost": round(sales[1], 2),
                "margin": round(sales[0] - sales[1], 2), "sold_count": sales[2],
                "average_margin": round((sales[0] - sales[1]) / sales[2], 2) if sales[2] else 0,
            }
        stock = conn.execute(
            """SELECT COALESCE(SUM(i.initial_quantity-COALESCE(x.sold,0)),0),
                      COALESCE(SUM(i.purchase_price*(i.initial_quantity-COALESCE(x.sold,0))/i.initial_quantity),0),
                      COALESCE(SUM(i.list_price*(i.initial_quantity-COALESCE(x.sold,0))),0)
               FROM items i
               LEFT JOIN (SELECT item_id,SUM(quantity) sold FROM sales
                          WHERE cancelled_at IS NULL AND finalized_at IS NOT NULL GROUP BY item_id) x ON x.item_id=i.id
               WHERE i.archived=0 AND (i.initial_quantity-COALESCE(x.sold,0))>0"""
        ).fetchone()
        platform_rows = conn.execute(
            """SELECT s.platform,SUM(s.quantity) count,ROUND(SUM(s.sale_price),2) revenue
               FROM sales s JOIN items i ON i.id=s.item_id
               WHERE s.cancelled_at IS NULL AND s.finalized_at IS NOT NULL AND i.archived=0 AND s.sale_date LIKE ?
               GROUP BY s.platform ORDER BY count DESC""",
            (year_prefix + "%",),
        ).fetchall()
        monthly = []
        for m in range(1, 13):
            pfx = f"{year:04d}-{m:02d}"
            mrow = period_metrics(pfx)
            monthly.append({"month": m, **mrow})
        recent = [dict(r) for r in conn.execute(
            "SELECT * FROM activity_log ORDER BY occurred_on DESC,id DESC LIMIT 8"
        )]
    return {
        "year": period_metrics_external(year_prefix),
        "month": period_metrics_external(month_prefix),
        "stock": {"count": stock[0], "cost": round(stock[1], 2), "potential": round(stock[2], 2)},
        "platforms": [dict(r) for r in platform_rows],
        "monthly": monthly,
        "recent": recent,
        "selected_year": year,
        "selected_month": month,
    }


def period_metrics_external(prefix):
    with db() as conn:
        purchases = conn.execute(
            """SELECT COALESCE(SUM(purchase_price),0),
               COUNT(DISTINCT CASE WHEN batch_id IS NULL THEN 'I'||id ELSE 'B'||batch_id END)
               FROM items WHERE archived=0 AND purchase_date LIKE ?""",
            (prefix + "%",),
        ).fetchone()
        sales = conn.execute(
            """SELECT COALESCE(SUM(s.sale_price),0),COALESCE(SUM(s.cost_basis),0),COALESCE(SUM(s.quantity),0)
               FROM sales s JOIN items i ON i.id=s.item_id WHERE s.cancelled_at IS NULL AND s.finalized_at IS NOT NULL
               AND i.archived=0 AND s.sale_date LIKE ?""", (prefix + "%",)
        ).fetchone()
    return {"spent": round(purchases[0], 2), "purchased_count": purchases[1],
            "revenue": round(sales[0], 2), "sold_cost": round(sales[1], 2),
            "margin": round(sales[0]-sales[1], 2), "sold_count": sales[2],
            "average_margin": round((sales[0]-sales[1])/sales[2], 2) if sales[2] else 0}


def top_sales(period="all", category="", platform=""):
    clauses = ["s.cancelled_at IS NULL", "s.finalized_at IS NOT NULL", "i.archived=0"]
    args = []
    if period != "all":
        clauses.append("s.sale_date LIKE ?")
        args.append(period + "%")
    if category:
        clauses.append("c.id=?")
        args.append(category)
    if platform:
        clauses.append("s.platform=?")
        args.append(platform)
    sql = """SELECT i.*,p.name product_name,c.name category_name,c.color category_color,
             s.id sale_id,s.sale_price,s.platform,s.sale_date,s.transaction_ref,s.finalized_at,
             s.quantity sale_quantity,s.cost_basis,ROUND(s.sale_price-s.cost_basis,2) margin,
             CASE WHEN s.cost_basis=0 THEN NULL ELSE ROUND((s.sale_price-s.cost_basis)*100.0/s.cost_basis,1) END margin_rate,
             (s.sale_date::date-i.listed_date::date) sale_days,
             CASE WHEN w.id IS NULL THEN 0 ELSE 1 END watched
             FROM sales s JOIN items i ON i.id=s.item_id JOIN products p ON p.id=i.product_id
             LEFT JOIN categories c ON c.id=p.category_id
             LEFT JOIN watchlist w ON w.product_id=p.id AND w.active=1 WHERE """ + " AND ".join(clauses)
    with db() as conn:
        rows = [dict(r) for r in conn.execute(sql, args)]
        repeat_rows = [dict(r) for r in conn.execute(
            """SELECT p.id product_id,p.name product_name,COUNT(*) sales_count,
               ROUND(AVG(s.sale_price-s.cost_basis),2) average_margin,
               ROUND(AVG(s.sale_date::date-i.listed_date::date),1) average_days,
               ROUND(SUM(s.sale_price-s.cost_basis),2) total_margin
               FROM sales s JOIN items i ON i.id=s.item_id JOIN products p ON p.id=i.product_id
               WHERE s.cancelled_at IS NULL AND s.finalized_at IS NOT NULL AND i.archived=0 GROUP BY p.id HAVING COUNT(*) >= 2
               ORDER BY total_margin DESC"""
        )]
    for row in rows:
        margin = row.get("margin") or 0
        rate = min(max(row.get("margin_rate") or 0, 0), 200)
        days = max(row.get("sale_days") or 0, 0)
        speed = max(0, 100 - days * 3)
        row["opportunity_score"] = round(min(100, margin * .55 + rate * .18 + speed * .28))
    return {"sales": rows, "repeats": repeat_rows}


def list_watchlist():
    with db() as conn:
        rows = conn.execute(
            """SELECT w.*,p.name product_name,c.name category_name,
               (SELECT ROUND(AVG(s.sale_price-s.cost_basis),2) FROM items i JOIN sales s ON s.item_id=i.id AND s.cancelled_at IS NULL AND s.finalized_at IS NOT NULL WHERE i.product_id=p.id) average_margin,
               (SELECT ROUND(AVG(s.sale_date::date-i.listed_date::date),1) FROM items i JOIN sales s ON s.item_id=i.id AND s.cancelled_at IS NULL AND s.finalized_at IS NOT NULL WHERE i.product_id=p.id) average_days,
               (SELECT ROUND(AVG(s.sale_price),2) FROM items i JOIN sales s ON s.item_id=i.id AND s.cancelled_at IS NULL AND s.finalized_at IS NOT NULL WHERE i.product_id=p.id) average_sale_price
               FROM watchlist w JOIN products p ON p.id=w.product_id
               LEFT JOIN categories c ON c.id=p.category_id ORDER BY w.active DESC,w.updated_at DESC"""
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["platforms"] = json.loads(item["platforms"])
        result.append(item)
    return result


def upsert_watch(payload):
    product_id = int(payload.get("product_id"))
    platforms = payload.get("platforms") or ["Vinted", "Leboncoin", "eBay"]
    max_price = payload.get("max_purchase_price")
    min_margin = payload.get("min_margin")
    max_price = None if max_price in (None, "") else money(max_price, "prix maximal")
    min_margin = None if min_margin in (None, "") else money(min_margin, "marge minimale")
    stamp = now_iso()
    values = (
        str(payload.get("keywords", "")).strip(), str(payload.get("excluded_words", "")).strip(),
        max_price, str(payload.get("desired_condition", "")).strip(),
        json.dumps(platforms, ensure_ascii=False), min_margin,
        str(payload.get("notes", "")).strip(), 1 if payload.get("active", True) else 0, stamp,
    )
    with db() as conn:
        if not conn.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
            raise KeyError("Produit introuvable.")
        conn.execute(
            """INSERT INTO watchlist(product_id,keywords,excluded_words,max_purchase_price,desired_condition,platforms,min_margin,notes,active,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(product_id) DO UPDATE SET keywords=excluded.keywords,excluded_words=excluded.excluded_words,
               max_purchase_price=excluded.max_purchase_price,desired_condition=excluded.desired_condition,
               platforms=excluded.platforms,min_margin=excluded.min_margin,notes=excluded.notes,
               active=excluded.active,updated_at=excluded.updated_at""",
            (product_id, *values[:-1], stamp, stamp),
        )
    return list_watchlist()


def accounting(start, end, platform="", kind="all"):
    clauses_purchase = ["i.archived=0", "i.purchase_date BETWEEN ? AND ?"]
    args_purchase = [start, end]
    clauses_sale = ["i.archived=0", "s.cancelled_at IS NULL", "s.finalized_at IS NOT NULL", "s.sale_date BETWEEN ? AND ?"]
    args_sale = [start, end]
    if platform:
        clauses_sale.append("s.platform=?")
        args_sale.append(platform)
    purchases = []
    sales = []
    with db() as conn:
        if kind in {"all", "achat"} and not platform:
            purchases = [dict(r) for r in conn.execute(
                """SELECT i.id,i.code,i.purchase_date date,'achat' kind,i.designation,c.name category,
                    '' platform,i.purchase_price amount,NULL sale_price,NULL margin,'' transaction_ref
                    FROM items i JOIN products p ON p.id=i.product_id LEFT JOIN categories c ON c.id=p.category_id
                    WHERE i.archived=0 AND i.batch_id IS NULL AND i.purchase_date BETWEEN ? AND ?
                    UNION ALL
                    SELECT 1000000000+b.id id,'LOT-'||LPAD(b.id::text,5,'0') code,b.purchase_date date,
                    'achat' kind,b.name||' ('||b.item_count||' articles)' designation,'Lot' category,
                    '' platform,b.total_price amount,NULL sale_price,NULL margin,'' transaction_ref
                    FROM purchase_batches b WHERE b.purchase_date BETWEEN ? AND ?
                    AND EXISTS(SELECT 1 FROM items i WHERE i.batch_id=b.id AND i.archived=0)""",
                [start, end, start, end])]
        if kind in {"all", "vente"}:
            sales = [dict(r) for r in conn.execute(
                f"""SELECT i.id,i.code,s.sale_date date,'vente' kind,i.designation,c.name category,
                    s.platform,s.sale_price amount,s.sale_price,s.sale_price-s.cost_basis margin,s.transaction_ref,
                    s.quantity
                    FROM sales s JOIN items i ON i.id=s.item_id JOIN products p ON p.id=i.product_id
                    LEFT JOIN categories c ON c.id=p.category_id WHERE {' AND '.join(clauses_sale)}""", args_sale)]
    rows = sorted(purchases + sales, key=lambda x: (x["date"], x["id"]))
    return {"rows": rows, "summary": {
        "purchases": round(sum(r["amount"] for r in purchases), 2),
        "revenue": round(sum(r["amount"] for r in sales), 2),
        "margin": round(sum(r["margin"] for r in sales), 2),
        "purchase_count": len(purchases), "sale_count": len(sales),
    }}
