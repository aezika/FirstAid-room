"""
ระบบจัดการใช้บริการห้องพยาบาลของบริษัท (Single-file Flask app)
รันด้วย: python app.py
"""

import sqlite3
from datetime import datetime, date
from collections import OrderedDict

from flask import Flask, g, request, redirect, url_for, flash, render_template
from jinja2 import DictLoader

DB_FILE = "clinic.db"

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-me"

DISEASE_GROUPS = [
    "ระบบทางเดินหายใจ (หวัด/ไอ/เจ็บคอ)",
    "ไข้",
    "ระบบทางเดินอาหาร (ปวดท้อง/ท้องเสีย)",
    "ปวดศีรษะ/ไมเกรน",
    "ปวดกล้ามเนื้อ/กระดูก",
    "บาดแผล/อุบัติเหตุ",
    "ผิวหนัง/ภูมิแพ้",
    "ความดัน/หัวใจ",
    "อื่นๆ",
]

STATUS_LABELS = {
    "pending": ("รออนุมัติ", "bg-amber-100 text-amber-800"),
    "approved": ("อนุมัติแล้ว รอพยาบาลตรวจ", "bg-blue-100 text-blue-800"),
    "rejected": ("ไม่อนุมัติ", "bg-red-100 text-red-800"),
    "completed": ("เสร็จสิ้น", "bg-green-100 text-green-800"),
}


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_db(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute_db(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    last_id = cur.lastrowid
    cur.close()
    return last_id


def init_db():
    db = sqlite3.connect(DB_FILE)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_code TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            department TEXT,
            position TEXT,
            phone TEXT
        );

        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            symptom TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            approver_name TEXT,
            approved_at TEXT,
            reject_reason TEXT,
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        );

        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL UNIQUE,
            nurse_name TEXT NOT NULL,
            diagnosis TEXT NOT NULL,
            disease_group TEXT NOT NULL,
            treatment_note TEXT,
            visit_date TEXT NOT NULL,
            FOREIGN KEY(request_id) REFERENCES requests(id)
        );

        CREATE TABLE IF NOT EXISTS medicines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            unit TEXT NOT NULL,
            stock_qty INTEGER NOT NULL DEFAULT 0,
            min_stock INTEGER NOT NULL DEFAULT 0,
            price REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS dispenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visit_id INTEGER NOT NULL,
            medicine_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY(visit_id) REFERENCES visits(id),
            FOREIGN KEY(medicine_id) REFERENCES medicines(id)
        );
        """
    )
    db.commit()

    # Seed demo data only if empty, so the app is usable immediately
    if db.execute("SELECT COUNT(*) c FROM employees").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO employees (emp_code, full_name, department, position, phone) VALUES (?,?,?,?,?)",
            [
                ("EMP001", "สมชาย ใจดี", "ฝ่ายผลิต", "พนักงานฝ่ายผลิต", "081-111-1111"),
                ("EMP002", "สมหญิง รักงาน", "ฝ่ายบัญชี", "เจ้าหน้าที่บัญชี", "081-222-2222"),
                ("EMP003", "วิชัย มั่นคง", "ฝ่ายไอที", "โปรแกรมเมอร์", "081-333-3333"),
            ],
        )
    if db.execute("SELECT COUNT(*) c FROM medicines").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO medicines (name, unit, stock_qty, min_stock, price) VALUES (?,?,?,?,?)",
            [
                ("พาราเซตามอล 500mg", "เม็ด", 200, 50, 0.5),
                ("ยาแก้แพ้ (คลอร์เฟนิรามีน)", "เม็ด", 100, 30, 0.5),
                ("ผงเกลือแร่ ORS", "ซอง", 40, 10, 5),
                ("ยาแก้ไอน้ำดำ", "ขวด", 15, 5, 20),
                ("แอลกอฮอล์ล้างแผล", "ขวด", 10, 3, 25),
                ("ยาธาตุน้ำขาว", "ขวด", 20, 5, 15),
                ("พลาสเตอร์ปิดแผล", "แผ่น", 150, 30, 1),
            ],
        )
    db.commit()
    db.close()


# --------------------------------------------------------------------------
# Templates (single-file: registered via DictLoader)
# --------------------------------------------------------------------------
BASE_HTML = """
<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}ระบบห้องพยาบาลบริษัท{% endblock %}</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>body{font-family:'Tahoma','Segoe UI',sans-serif;}</style>
</head>
<body class="bg-slate-50 text-slate-800 min-h-screen">
<nav class="bg-teal-700 text-white shadow">
  <div class="max-w-6xl mx-auto px-4">
    <div class="flex items-center justify-between h-16">
      <a href="{{ url_for('index') }}" class="font-bold text-lg flex items-center gap-2">
        <span>🏥</span><span>ห้องพยาบาลบริษัท</span>
      </a>
      <div class="hidden md:flex gap-1 text-sm">
        <a href="{{ url_for('index') }}" class="px-3 py-2 rounded hover:bg-teal-600 {{ 'bg-teal-800' if request.path=='/' }}">หน้าหลัก</a>
        <a href="{{ url_for('list_employees') }}" class="px-3 py-2 rounded hover:bg-teal-600 {{ 'bg-teal-800' if '/employees' in request.path }}">พนักงาน</a>
        <a href="{{ url_for('list_requests') }}" class="px-3 py-2 rounded hover:bg-teal-600 {{ 'bg-teal-800' if request.path.startswith('/requests') }}">คำขอใช้บริการ</a>
        <a href="{{ url_for('nurse_queue') }}" class="px-3 py-2 rounded hover:bg-teal-600 {{ 'bg-teal-800' if request.path.startswith('/nurse') }}">งานพยาบาล</a>
        <a href="{{ url_for('list_medicines') }}" class="px-3 py-2 rounded hover:bg-teal-600 {{ 'bg-teal-800' if request.path.startswith('/medicines') }}">คลังยา</a>
        <a href="{{ url_for('monthly_report') }}" class="px-3 py-2 rounded hover:bg-teal-600 {{ 'bg-teal-800' if request.path.startswith('/reports') }}">รายงานประจำเดือน</a>
      </div>
    </div>
    <div class="md:hidden flex flex-wrap gap-1 pb-2 text-xs">
        <a href="{{ url_for('index') }}" class="px-2 py-1 rounded bg-teal-800">หน้าหลัก</a>
        <a href="{{ url_for('list_employees') }}" class="px-2 py-1 rounded bg-teal-800">พนักงาน</a>
        <a href="{{ url_for('list_requests') }}" class="px-2 py-1 rounded bg-teal-800">คำขอ</a>
        <a href="{{ url_for('nurse_queue') }}" class="px-2 py-1 rounded bg-teal-800">พยาบาล</a>
        <a href="{{ url_for('list_medicines') }}" class="px-2 py-1 rounded bg-teal-800">คลังยา</a>
        <a href="{{ url_for('monthly_report') }}" class="px-2 py-1 rounded bg-teal-800">รายงาน</a>
    </div>
  </div>
</nav>

<main class="max-w-6xl mx-auto px-4 py-6">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, message in messages %}
        <div class="mb-4 px-4 py-3 rounded-lg text-sm border
          {{ 'bg-green-50 text-green-800 border-green-200' if category=='success'
             else 'bg-red-50 text-red-800 border-red-200' if category=='error'
             else 'bg-blue-50 text-blue-800 border-blue-200' }}">
          {{ message }}
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}

  {% block content %}{% endblock %}
</main>

<footer class="text-center text-xs text-slate-400 py-6">ระบบจัดการใช้บริการห้องพยาบาล — Prototype (ไม่มีระบบล็อกอิน)</footer>
</body>
</html>
"""

INDEX_HTML = """
{% extends "base.html" %}
{% block title %}หน้าหลัก - ห้องพยาบาลบริษัท{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-6">ภาพรวมวันนี้</h1>

<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
  <div class="bg-white rounded-xl shadow p-4 border-l-4 border-amber-400">
    <p class="text-sm text-slate-500">รออนุมัติ</p>
    <p class="text-3xl font-bold text-amber-600">{{ stats.pending }}</p>
  </div>
  <div class="bg-white rounded-xl shadow p-4 border-l-4 border-blue-400">
    <p class="text-sm text-slate-500">รอพยาบาลตรวจ</p>
    <p class="text-3xl font-bold text-blue-600">{{ stats.approved }}</p>
  </div>
  <div class="bg-white rounded-xl shadow p-4 border-l-4 border-green-400">
    <p class="text-sm text-slate-500">ตรวจเสร็จวันนี้</p>
    <p class="text-3xl font-bold text-green-600">{{ stats.completed_today }}</p>
  </div>
  <div class="bg-white rounded-xl shadow p-4 border-l-4 border-red-400">
    <p class="text-sm text-slate-500">ยาใกล้หมด</p>
    <p class="text-3xl font-bold text-red-600">{{ stats.low_stock }}</p>
  </div>
</div>

<div class="grid md:grid-cols-2 gap-6">
  <div class="bg-white rounded-xl shadow p-5">
    <div class="flex justify-between items-center mb-3">
      <h2 class="font-semibold">คำขอล่าสุด</h2>
      <a href="{{ url_for('new_request') }}" class="text-sm bg-teal-600 text-white px-3 py-1.5 rounded hover:bg-teal-700">+ ยื่นคำขอใหม่</a>
    </div>
    {% if recent_requests %}
    <ul class="divide-y">
      {% for r in recent_requests %}
      <li class="py-2 flex justify-between items-center text-sm">
        <div>
          <p class="font-medium">{{ r.full_name }} <span class="text-slate-400">({{ r.emp_code }})</span></p>
          <p class="text-slate-500">{{ r.symptom }}</p>
        </div>
        <span class="text-xs px-2 py-1 rounded-full {{ status_labels[r.status][1] }}">{{ status_labels[r.status][0] }}</span>
      </li>
      {% endfor %}
    </ul>
    {% else %}
    <p class="text-slate-400 text-sm">ยังไม่มีคำขอ</p>
    {% endif %}
  </div>

  <div class="bg-white rounded-xl shadow p-5">
    <h2 class="font-semibold mb-3">ยาที่ใกล้หมดสต็อก</h2>
    {% if low_stock_meds %}
    <ul class="divide-y">
      {% for m in low_stock_meds %}
      <li class="py-2 flex justify-between text-sm">
        <span>{{ m.name }}</span>
        <span class="text-red-600 font-semibold">{{ m.stock_qty }} {{ m.unit }} (ขั้นต่ำ {{ m.min_stock }})</span>
      </li>
      {% endfor %}
    </ul>
    {% else %}
    <p class="text-slate-400 text-sm">สต็อกยาทุกรายการเพียงพอ</p>
    {% endif %}
  </div>
</div>
{% endblock %}
"""

EMPLOYEES_HTML = """
{% extends "base.html" %}
{% block title %}พนักงาน - ห้องพยาบาลบริษัท{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-6">รายละเอียดพนักงาน</h1>

<div class="grid md:grid-cols-3 gap-6">
  <div class="md:col-span-1 bg-white rounded-xl shadow p-5 h-fit">
    <h2 class="font-semibold mb-3">เพิ่มพนักงานใหม่</h2>
    <form method="post" action="{{ url_for('add_employee') }}" class="space-y-3">
      <div>
        <label class="text-sm text-slate-600">รหัสพนักงาน</label>
        <input name="emp_code" required class="w-full border rounded px-3 py-2 text-sm">
      </div>
      <div>
        <label class="text-sm text-slate-600">ชื่อ-นามสกุล</label>
        <input name="full_name" required class="w-full border rounded px-3 py-2 text-sm">
      </div>
      <div>
        <label class="text-sm text-slate-600">แผนก</label>
        <input name="department" class="w-full border rounded px-3 py-2 text-sm">
      </div>
      <div>
        <label class="text-sm text-slate-600">ตำแหน่ง</label>
        <input name="position" class="w-full border rounded px-3 py-2 text-sm">
      </div>
      <div>
        <label class="text-sm text-slate-600">เบอร์โทร</label>
        <input name="phone" class="w-full border rounded px-3 py-2 text-sm">
      </div>
      <button class="w-full bg-teal-600 text-white rounded py-2 text-sm hover:bg-teal-700">บันทึก</button>
    </form>
  </div>

  <div class="md:col-span-2 bg-white rounded-xl shadow overflow-x-auto">
    <table class="w-full text-sm">
      <thead class="bg-slate-100 text-slate-600">
        <tr>
          <th class="text-left px-4 py-2">รหัส</th>
          <th class="text-left px-4 py-2">ชื่อ-นามสกุล</th>
          <th class="text-left px-4 py-2">แผนก</th>
          <th class="text-left px-4 py-2">ตำแหน่ง</th>
          <th class="text-left px-4 py-2">โทร</th>
          <th class="px-4 py-2"></th>
        </tr>
      </thead>
      <tbody class="divide-y">
        {% for e in employees %}
        <tr>
          <td class="px-4 py-2">{{ e.emp_code }}</td>
          <td class="px-4 py-2">{{ e.full_name }}</td>
          <td class="px-4 py-2">{{ e.department }}</td>
          <td class="px-4 py-2">{{ e.position }}</td>
          <td class="px-4 py-2">{{ e.phone }}</td>
          <td class="px-4 py-2 text-right">
            <form method="post" action="{{ url_for('delete_employee', emp_id=e.id) }}" onsubmit="return confirm('ลบพนักงานนี้?');">
              <button class="text-red-500 hover:underline text-xs">ลบ</button>
            </form>
          </td>
        </tr>
        {% else %}
        <tr><td colspan="6" class="px-4 py-6 text-center text-slate-400">ยังไม่มีข้อมูลพนักงาน</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
"""

REQUESTS_HTML = """
{% extends "base.html" %}
{% block title %}คำขอใช้บริการ - ห้องพยาบาลบริษัท{% endblock %}
{% block content %}
<div class="flex justify-between items-center mb-6">
  <h1 class="text-2xl font-bold">คำขอใช้บริการห้องพยาบาล</h1>
  <a href="{{ url_for('new_request') }}" class="bg-teal-600 text-white px-4 py-2 rounded hover:bg-teal-700 text-sm">+ ยื่นคำขอใหม่</a>
</div>

<div class="bg-white rounded-xl shadow overflow-x-auto">
  <table class="w-full text-sm">
    <thead class="bg-slate-100 text-slate-600">
      <tr>
        <th class="text-left px-4 py-2">วันที่/เวลา</th>
        <th class="text-left px-4 py-2">พนักงาน</th>
        <th class="text-left px-4 py-2">อาการ</th>
        <th class="text-left px-4 py-2">สถานะ</th>
        <th class="text-left px-4 py-2">ผู้อนุมัติ</th>
        <th class="px-4 py-2">การดำเนินการ</th>
      </tr>
    </thead>
    <tbody class="divide-y">
      {% for r in requests %}
      <tr>
        <td class="px-4 py-2 whitespace-nowrap">{{ r.requested_at }}</td>
        <td class="px-4 py-2">{{ r.full_name }} <span class="text-slate-400">({{ r.emp_code }})</span></td>
        <td class="px-4 py-2 max-w-xs truncate" title="{{ r.symptom }}">{{ r.symptom }}</td>
        <td class="px-4 py-2">
          <span class="text-xs px-2 py-1 rounded-full {{ status_labels[r.status][1] }}">{{ status_labels[r.status][0] }}</span>
          {% if r.status == 'rejected' and r.reject_reason %}<div class="text-xs text-red-500 mt-1">เหตุผล: {{ r.reject_reason }}</div>{% endif %}
        </td>
        <td class="px-4 py-2">{{ r.approver_name or '-' }}</td>
        <td class="px-4 py-2 text-right whitespace-nowrap">
          {% if r.status == 'pending' %}
            <form method="post" action="{{ url_for('approve_request', req_id=r.id) }}" class="inline">
              <input type="hidden" name="approver_name" value="หัวหน้างาน">
              <button class="text-green-600 hover:underline text-xs mr-2">อนุมัติ</button>
            </form>
            <button onclick="document.getElementById('reject-{{ r.id }}').classList.toggle('hidden')" class="text-red-500 hover:underline text-xs">ไม่อนุมัติ</button>
            <form id="reject-{{ r.id }}" method="post" action="{{ url_for('reject_request', req_id=r.id) }}" class="hidden mt-2 flex gap-1">
              <input name="reject_reason" placeholder="เหตุผล" class="border rounded px-2 py-1 text-xs w-32">
              <button class="bg-red-500 text-white text-xs px-2 py-1 rounded">ยืนยัน</button>
            </form>
          {% elif r.status == 'approved' %}
            <a href="{{ url_for('diagnose_form', req_id=r.id) }}" class="text-blue-600 hover:underline text-xs">บันทึกตรวจรักษา</a>
          {% elif r.status == 'completed' %}
            <a href="{{ url_for('visit_detail', req_id=r.id) }}" class="text-slate-500 hover:underline text-xs">ดูรายละเอียด</a>
          {% else %}
            <span class="text-slate-300 text-xs">-</span>
          {% endif %}
        </td>
      </tr>
      {% else %}
      <tr><td colspan="6" class="px-4 py-6 text-center text-slate-400">ยังไม่มีคำขอ</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
"""

NEW_REQUEST_HTML = """
{% extends "base.html" %}
{% block title %}ยื่นคำขอใช้บริการ{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-6">ยื่นคำขอใช้บริการห้องพยาบาล</h1>
<div class="bg-white rounded-xl shadow p-6 max-w-lg">
  <form method="post" class="space-y-4">
    <div>
      <label class="text-sm text-slate-600">พนักงานผู้ขอใช้บริการ</label>
      <select name="employee_id" required class="w-full border rounded px-3 py-2 text-sm">
        <option value="">-- เลือกพนักงาน --</option>
        {% for e in employees %}
        <option value="{{ e.id }}">{{ e.emp_code }} - {{ e.full_name }} ({{ e.department }})</option>
        {% endfor %}
      </select>
    </div>
    <div>
      <label class="text-sm text-slate-600">อาการเบื้องต้น</label>
      <textarea name="symptom" required rows="4" class="w-full border rounded px-3 py-2 text-sm" placeholder="เช่น ปวดหัว มีไข้ ตั้งแต่เช้า"></textarea>
    </div>
    <button class="bg-teal-600 text-white px-4 py-2 rounded hover:bg-teal-700 text-sm">ส่งคำขอ (รอหัวหน้างานอนุมัติ)</button>
  </form>
</div>
{% endblock %}
"""

NURSE_QUEUE_HTML = """
{% extends "base.html" %}
{% block title %}งานพยาบาล - คิวรอตรวจ{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-6">คิวรอตรวจรักษา (อนุมัติแล้ว)</h1>
<div class="bg-white rounded-xl shadow overflow-x-auto">
  <table class="w-full text-sm">
    <thead class="bg-slate-100 text-slate-600">
      <tr>
        <th class="text-left px-4 py-2">วันที่ขอ</th>
        <th class="text-left px-4 py-2">พนักงาน</th>
        <th class="text-left px-4 py-2">แผนก</th>
        <th class="text-left px-4 py-2">อาการ</th>
        <th class="px-4 py-2"></th>
      </tr>
    </thead>
    <tbody class="divide-y">
      {% for r in queue %}
      <tr>
        <td class="px-4 py-2 whitespace-nowrap">{{ r.requested_at }}</td>
        <td class="px-4 py-2">{{ r.full_name }} ({{ r.emp_code }})</td>
        <td class="px-4 py-2">{{ r.department }}</td>
        <td class="px-4 py-2">{{ r.symptom }}</td>
        <td class="px-4 py-2 text-right">
          <a href="{{ url_for('diagnose_form', req_id=r.id) }}" class="bg-blue-600 text-white text-xs px-3 py-1.5 rounded hover:bg-blue-700">บันทึกตรวจรักษา</a>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="5" class="px-4 py-6 text-center text-slate-400">ไม่มีคิวรอตรวจ</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<h2 class="text-xl font-bold mt-8 mb-4">ประวัติการตรวจล่าสุด</h2>
<div class="bg-white rounded-xl shadow overflow-x-auto">
  <table class="w-full text-sm">
    <thead class="bg-slate-100 text-slate-600">
      <tr>
        <th class="text-left px-4 py-2">วันที่ตรวจ</th>
        <th class="text-left px-4 py-2">พนักงาน</th>
        <th class="text-left px-4 py-2">กลุ่มโรค</th>
        <th class="text-left px-4 py-2">วินิจฉัย</th>
        <th class="px-4 py-2"></th>
      </tr>
    </thead>
    <tbody class="divide-y">
      {% for v in recent_visits %}
      <tr>
        <td class="px-4 py-2 whitespace-nowrap">{{ v.visit_date }}</td>
        <td class="px-4 py-2">{{ v.full_name }}</td>
        <td class="px-4 py-2">{{ v.disease_group }}</td>
        <td class="px-4 py-2 max-w-xs truncate" title="{{ v.diagnosis }}">{{ v.diagnosis }}</td>
        <td class="px-4 py-2 text-right"><a href="{{ url_for('visit_detail', req_id=v.request_id) }}" class="text-blue-600 hover:underline text-xs">ดู</a></td>
      </tr>
      {% else %}
      <tr><td colspan="5" class="px-4 py-6 text-center text-slate-400">ยังไม่มีประวัติ</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
"""

DIAGNOSE_HTML = """
{% extends "base.html" %}
{% block title %}บันทึกตรวจรักษา{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-2">บันทึกการตรวจรักษา</h1>
<p class="text-slate-500 mb-6">{{ req.full_name }} ({{ req.emp_code }}) - {{ req.department }} | อาการที่แจ้ง: {{ req.symptom }}</p>

<form method="post" class="bg-white rounded-xl shadow p-6 space-y-5" id="diagForm">
  <div>
    <label class="text-sm text-slate-600">ชื่อพยาบาลผู้ตรวจ</label>
    <input name="nurse_name" required class="w-full border rounded px-3 py-2 text-sm" placeholder="พยาบาลประจำ">
  </div>
  <div>
    <label class="text-sm text-slate-600">กลุ่มโรค / อาการหลัก</label>
    <select name="disease_group" required class="w-full border rounded px-3 py-2 text-sm">
      {% for g in disease_groups %}
      <option value="{{ g }}">{{ g }}</option>
      {% endfor %}
    </select>
  </div>
  <div>
    <label class="text-sm text-slate-600">ผลการวินิจฉัย</label>
    <textarea name="diagnosis" required rows="3" class="w-full border rounded px-3 py-2 text-sm"></textarea>
  </div>
  <div>
    <label class="text-sm text-slate-600">การรักษา / คำแนะนำ</label>
    <textarea name="treatment_note" rows="2" class="w-full border rounded px-3 py-2 text-sm"></textarea>
  </div>

  <div>
    <div class="flex justify-between items-center mb-2">
      <label class="text-sm text-slate-600 font-medium">จ่ายยา (ตัดสต็อกอัตโนมัติ)</label>
      <button type="button" onclick="addMedRow()" class="text-xs bg-slate-100 hover:bg-slate-200 px-2 py-1 rounded">+ เพิ่มรายการยา</button>
    </div>
    <div id="medRows" class="space-y-2"></div>
  </div>

  <button class="bg-teal-600 text-white px-4 py-2 rounded hover:bg-teal-700 text-sm">บันทึกผลการตรวจ</button>
</form>

<template id="medRowTpl">
  <div class="flex gap-2 items-center med-row">
    <select name="medicine_id[]" class="flex-1 border rounded px-3 py-2 text-sm">
      <option value="">-- ไม่จ่ายยา --</option>
      {% for m in medicines %}
      <option value="{{ m.id }}">{{ m.name }} (คงเหลือ {{ m.stock_qty }} {{ m.unit }})</option>
      {% endfor %}
    </select>
    <input type="number" name="quantity[]" min="1" value="1" class="w-24 border rounded px-3 py-2 text-sm" placeholder="จำนวน">
    <button type="button" onclick="this.parentElement.remove()" class="text-red-400 hover:text-red-600 text-xs px-2">ลบ</button>
  </div>
</template>

<script>
function addMedRow(){
  const tpl = document.getElementById('medRowTpl');
  document.getElementById('medRows').appendChild(tpl.content.cloneNode(true));
}
addMedRow();
</script>
{% endblock %}
"""

VISIT_DETAIL_HTML = """
{% extends "base.html" %}
{% block title %}รายละเอียดการตรวจ{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-6">รายละเอียดการตรวจรักษา</h1>
<div class="bg-white rounded-xl shadow p-6 space-y-4 max-w-2xl">
  <div class="grid grid-cols-2 gap-4 text-sm">
    <div><span class="text-slate-500">พนักงาน:</span> {{ req.full_name }} ({{ req.emp_code }})</div>
    <div><span class="text-slate-500">แผนก:</span> {{ req.department }}</div>
    <div><span class="text-slate-500">วันที่ขอใช้บริการ:</span> {{ req.requested_at }}</div>
    <div><span class="text-slate-500">ผู้อนุมัติ:</span> {{ req.approver_name }}</div>
  </div>
  <hr>
  <div class="text-sm space-y-2">
    <p><span class="text-slate-500">อาการที่แจ้ง:</span> {{ req.symptom }}</p>
    <p><span class="text-slate-500">พยาบาลผู้ตรวจ:</span> {{ visit.nurse_name }}</p>
    <p><span class="text-slate-500">วันที่ตรวจ:</span> {{ visit.visit_date }}</p>
    <p><span class="text-slate-500">กลุ่มโรค:</span> <span class="px-2 py-0.5 bg-teal-50 text-teal-700 rounded">{{ visit.disease_group }}</span></p>
    <p><span class="text-slate-500">ผลวินิจฉัย:</span> {{ visit.diagnosis }}</p>
    <p><span class="text-slate-500">การรักษา/คำแนะนำ:</span> {{ visit.treatment_note or '-' }}</p>
  </div>
  <hr>
  <div>
    <p class="text-sm text-slate-500 mb-2">รายการยาที่จ่าย</p>
    {% if dispenses %}
    <table class="w-full text-sm">
      <thead class="text-left text-slate-500">
        <tr><th class="py-1">ชื่อยา</th><th class="py-1">จำนวน</th></tr>
      </thead>
      <tbody class="divide-y">
        {% for d in dispenses %}
        <tr><td class="py-1">{{ d.name }}</td><td class="py-1">{{ d.quantity }} {{ d.unit }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="text-slate-400 text-sm">ไม่มีการจ่ายยา</p>
    {% endif %}
  </div>
</div>
{% endblock %}
"""

MEDICINES_HTML = """
{% extends "base.html" %}
{% block title %}คลังยา{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-6">คลังยา (Stock)</h1>

<div class="grid md:grid-cols-3 gap-6">
  <div class="md:col-span-1 bg-white rounded-xl shadow p-5 h-fit">
    <h2 class="font-semibold mb-3">เพิ่มรายการยาใหม่</h2>
    <form method="post" action="{{ url_for('add_medicine') }}" class="space-y-3">
      <div>
        <label class="text-sm text-slate-600">ชื่อยา</label>
        <input name="name" required class="w-full border rounded px-3 py-2 text-sm">
      </div>
      <div>
        <label class="text-sm text-slate-600">หน่วย</label>
        <input name="unit" required placeholder="เม็ด/ขวด/ซอง" class="w-full border rounded px-3 py-2 text-sm">
      </div>
      <div>
        <label class="text-sm text-slate-600">จำนวนคงเหลือเริ่มต้น</label>
        <input type="number" name="stock_qty" value="0" min="0" class="w-full border rounded px-3 py-2 text-sm">
      </div>
      <div>
        <label class="text-sm text-slate-600">สต็อกขั้นต่ำ (แจ้งเตือน)</label>
        <input type="number" name="min_stock" value="0" min="0" class="w-full border rounded px-3 py-2 text-sm">
      </div>
      <div>
        <label class="text-sm text-slate-600">ราคา/หน่วย (บาท)</label>
        <input type="number" step="0.01" name="price" value="0" class="w-full border rounded px-3 py-2 text-sm">
      </div>
      <button class="w-full bg-teal-600 text-white rounded py-2 text-sm hover:bg-teal-700">บันทึก</button>
    </form>
  </div>

  <div class="md:col-span-2 bg-white rounded-xl shadow overflow-x-auto">
    <table class="w-full text-sm">
      <thead class="bg-slate-100 text-slate-600">
        <tr>
          <th class="text-left px-4 py-2">ชื่อยา</th>
          <th class="text-left px-4 py-2">หน่วย</th>
          <th class="text-left px-4 py-2">คงเหลือ</th>
          <th class="text-left px-4 py-2">ขั้นต่ำ</th>
          <th class="text-left px-4 py-2">เติมสต็อก</th>
        </tr>
      </thead>
      <tbody class="divide-y">
        {% for m in medicines %}
        <tr class="{{ 'bg-red-50' if m.stock_qty <= m.min_stock }}">
          <td class="px-4 py-2">{{ m.name }}</td>
          <td class="px-4 py-2">{{ m.unit }}</td>
          <td class="px-4 py-2 font-semibold {{ 'text-red-600' if m.stock_qty <= m.min_stock else 'text-slate-700' }}">{{ m.stock_qty }}</td>
          <td class="px-4 py-2">{{ m.min_stock }}</td>
          <td class="px-4 py-2">
            <form method="post" action="{{ url_for('restock_medicine', med_id=m.id) }}" class="flex gap-1">
              <input type="number" name="amount" min="1" value="10" class="w-20 border rounded px-2 py-1 text-xs">
              <button class="bg-slate-100 hover:bg-slate-200 text-xs px-2 py-1 rounded">+ เติม</button>
            </form>
          </td>
        </tr>
        {% else %}
        <tr><td colspan="5" class="px-4 py-6 text-center text-slate-400">ยังไม่มีรายการยา</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
"""

REPORT_HTML = """
{% extends "base.html" %}
{% block title %}รายงานประจำเดือน{% endblock %}
{% block content %}
<div class="flex flex-wrap justify-between items-center gap-3 mb-6">
  <h1 class="text-2xl font-bold">รายงานวิเคราะห์ประจำเดือน</h1>
  <form method="get" class="flex gap-2 items-center text-sm">
    <label class="text-slate-600">เลือกเดือน:</label>
    <input type="month" name="month" value="{{ month }}" class="border rounded px-3 py-2" onchange="this.form.submit()">
  </form>
</div>

<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
  <div class="bg-white rounded-xl shadow p-4">
    <p class="text-sm text-slate-500">จำนวนครั้งที่เข้ารับบริการ</p>
    <p class="text-3xl font-bold text-teal-700">{{ total_visits }}</p>
  </div>
  <div class="bg-white rounded-xl shadow p-4">
    <p class="text-sm text-slate-500">พนักงานที่มาใช้บริการ (ไม่ซ้ำ)</p>
    <p class="text-3xl font-bold text-teal-700">{{ unique_employees }}</p>
  </div>
  <div class="bg-white rounded-xl shadow p-4">
    <p class="text-sm text-slate-500">กลุ่มโรคที่พบมากที่สุด</p>
    <p class="text-lg font-bold text-teal-700">{{ top_disease or '-' }}</p>
  </div>
  <div class="bg-white rounded-xl shadow p-4">
    <p class="text-sm text-slate-500">ยาที่จ่ายมากที่สุด</p>
    <p class="text-lg font-bold text-teal-700">{{ top_medicine or '-' }}</p>
  </div>
</div>

<div class="grid md:grid-cols-2 gap-6 mb-8">
  <div class="bg-white rounded-xl shadow p-5">
    <h2 class="font-semibold mb-3">ความถี่ของกลุ่มโรค</h2>
    {% if disease_stats %}
    <canvas id="diseaseChart" height="220"></canvas>
    {% else %}
    <p class="text-slate-400 text-sm">ไม่มีข้อมูลในเดือนนี้</p>
    {% endif %}
  </div>
  <div class="bg-white rounded-xl shadow p-5">
    <h2 class="font-semibold mb-3">ความถี่การจ่ายยา</h2>
    {% if medicine_stats %}
    <canvas id="medChart" height="220"></canvas>
    {% else %}
    <p class="text-slate-400 text-sm">ไม่มีข้อมูลในเดือนนี้</p>
    {% endif %}
  </div>
</div>

<div class="grid md:grid-cols-2 gap-6">
  <div class="bg-white rounded-xl shadow overflow-x-auto">
    <table class="w-full text-sm">
      <thead class="bg-slate-100 text-slate-600"><tr><th class="text-left px-4 py-2">กลุ่มโรค</th><th class="text-left px-4 py-2">จำนวนครั้ง</th></tr></thead>
      <tbody class="divide-y">
        {% for d in disease_stats %}
        <tr><td class="px-4 py-2">{{ d.disease_group }}</td><td class="px-4 py-2">{{ d.c }}</td></tr>
        {% else %}
        <tr><td colspan="2" class="px-4 py-6 text-center text-slate-400">ไม่มีข้อมูล</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  <div class="bg-white rounded-xl shadow overflow-x-auto">
    <table class="w-full text-sm">
      <thead class="bg-slate-100 text-slate-600"><tr><th class="text-left px-4 py-2">ชื่อยา</th><th class="text-left px-4 py-2">จำนวนที่จ่าย</th></tr></thead>
      <tbody class="divide-y">
        {% for m in medicine_stats %}
        <tr><td class="px-4 py-2">{{ m.name }}</td><td class="px-4 py-2">{{ m.qty }} {{ m.unit }}</td></tr>
        {% else %}
        <tr><td colspan="2" class="px-4 py-6 text-center text-slate-400">ไม่มีข้อมูล</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

<script>
{% if disease_stats %}
new Chart(document.getElementById('diseaseChart'), {
  type: 'pie',
  data: {
    labels: {{ disease_labels|tojson }},
    datasets: [{ data: {{ disease_values|tojson }},
      backgroundColor: ['#0d9488','#0891b2','#2563eb','#7c3aed','#db2777','#dc2626','#d97706','#65a30d','#475569'] }]
  },
  options: { plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 10 } } } } }
});
{% endif %}
{% if medicine_stats %}
new Chart(document.getElementById('medChart'), {
  type: 'bar',
  data: {
    labels: {{ med_labels|tojson }},
    datasets: [{ label: 'จำนวนที่จ่าย', data: {{ med_values|tojson }}, backgroundColor: '#0d9488' }]
  },
  options: { indexAxis: 'y', plugins: { legend: { display: false } } }
});
{% endif %}
</script>
{% endblock %}
"""

app.jinja_loader = DictLoader(
    {
        "base.html": BASE_HTML,
        "index.html": INDEX_HTML,
        "employees.html": EMPLOYEES_HTML,
        "requests.html": REQUESTS_HTML,
        "new_request.html": NEW_REQUEST_HTML,
        "nurse_queue.html": NURSE_QUEUE_HTML,
        "diagnose.html": DIAGNOSE_HTML,
        "visit_detail.html": VISIT_DETAIL_HTML,
        "medicines.html": MEDICINES_HTML,
        "report.html": REPORT_HTML,
    }
)


# --------------------------------------------------------------------------
# Routes: Dashboard
# --------------------------------------------------------------------------
@app.route("/")
def index():
    pending = query_db("SELECT COUNT(*) c FROM requests WHERE status='pending'", one=True)["c"]
    approved = query_db("SELECT COUNT(*) c FROM requests WHERE status='approved'", one=True)["c"]
    today = date.today().isoformat()
    completed_today = query_db(
        "SELECT COUNT(*) c FROM visits WHERE substr(visit_date,1,10)=?", (today,), one=True
    )["c"]
    low_stock = query_db(
        "SELECT COUNT(*) c FROM medicines WHERE stock_qty <= min_stock", one=True
    )["c"]

    recent_requests = query_db(
        """SELECT r.*, e.full_name, e.emp_code FROM requests r
           JOIN employees e ON e.id = r.employee_id
           ORDER BY r.id DESC LIMIT 6"""
    )
    low_stock_meds = query_db(
        "SELECT * FROM medicines WHERE stock_qty <= min_stock ORDER BY stock_qty ASC LIMIT 6"
    )

    return render_template(
        "index.html",
        stats={
            "pending": pending,
            "approved": approved,
            "completed_today": completed_today,
            "low_stock": low_stock,
        },
        recent_requests=recent_requests,
        low_stock_meds=low_stock_meds,
        status_labels=STATUS_LABELS,
    )


# --------------------------------------------------------------------------
# Routes: Employees
# --------------------------------------------------------------------------
@app.route("/employees")
def list_employees():
    employees = query_db("SELECT * FROM employees ORDER BY id DESC")
    return render_template("employees.html", employees=employees)


@app.route("/employees/add", methods=["POST"])
def add_employee():
    emp_code = request.form["emp_code"].strip()
    full_name = request.form["full_name"].strip()
    department = request.form.get("department", "").strip()
    position = request.form.get("position", "").strip()
    phone = request.form.get("phone", "").strip()

    if not emp_code or not full_name:
        flash("กรุณากรอกรหัสพนักงานและชื่อ-นามสกุล", "error")
        return redirect(url_for("list_employees"))

    try:
        execute_db(
            "INSERT INTO employees (emp_code, full_name, department, position, phone) VALUES (?,?,?,?,?)",
            (emp_code, full_name, department, position, phone),
        )
        flash("เพิ่มพนักงานเรียบร้อยแล้ว", "success")
    except sqlite3.IntegrityError:
        flash(f"รหัสพนักงาน {emp_code} มีอยู่แล้ว", "error")

    return redirect(url_for("list_employees"))


@app.route("/employees/<int:emp_id>/delete", methods=["POST"])
def delete_employee(emp_id):
    in_use = query_db(
        "SELECT COUNT(*) c FROM requests WHERE employee_id=?", (emp_id,), one=True
    )["c"]
    if in_use:
        flash("ไม่สามารถลบพนักงานที่มีประวัติการใช้บริการได้", "error")
    else:
        execute_db("DELETE FROM employees WHERE id=?", (emp_id,))
        flash("ลบพนักงานเรียบร้อยแล้ว", "success")
    return redirect(url_for("list_employees"))


# --------------------------------------------------------------------------
# Routes: Requests (ผู้ขอใช้บริการ + อนุมัติหัวหน้างาน)
# --------------------------------------------------------------------------
@app.route("/requests")
def list_requests():
    requests_ = query_db(
        """SELECT r.*, e.full_name, e.emp_code FROM requests r
           JOIN employees e ON e.id = r.employee_id
           ORDER BY r.id DESC"""
    )
    return render_template("requests.html", requests=requests_, status_labels=STATUS_LABELS)


@app.route("/requests/new", methods=["GET", "POST"])
def new_request():
    if request.method == "POST":
        employee_id = request.form.get("employee_id")
        symptom = request.form.get("symptom", "").strip()
        if not employee_id or not symptom:
            flash("กรุณาเลือกพนักงานและกรอกอาการ", "error")
            return redirect(url_for("new_request"))

        execute_db(
            "INSERT INTO requests (employee_id, symptom, requested_at, status) VALUES (?,?,?,'pending')",
            (employee_id, symptom, datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        flash("ส่งคำขอใช้บริการเรียบร้อยแล้ว รอหัวหน้างานอนุมัติ", "success")
        return redirect(url_for("list_requests"))

    employees = query_db("SELECT * FROM employees ORDER BY full_name")
    return render_template("new_request.html", employees=employees)


@app.route("/requests/<int:req_id>/approve", methods=["POST"])
def approve_request(req_id):
    approver_name = request.form.get("approver_name", "หัวหน้างาน")
    execute_db(
        "UPDATE requests SET status='approved', approver_name=?, approved_at=? WHERE id=?",
        (approver_name, datetime.now().strftime("%Y-%m-%d %H:%M"), req_id),
    )
    flash("อนุมัติคำขอเรียบร้อยแล้ว", "success")
    return redirect(url_for("list_requests"))


@app.route("/requests/<int:req_id>/reject", methods=["POST"])
def reject_request(req_id):
    reason = request.form.get("reject_reason", "").strip()
    execute_db(
        "UPDATE requests SET status='rejected', reject_reason=?, approved_at=? WHERE id=?",
        (reason, datetime.now().strftime("%Y-%m-%d %H:%M"), req_id),
    )
    flash("ปฏิเสธคำขอเรียบร้อยแล้ว", "success")
    return redirect(url_for("list_requests"))


# --------------------------------------------------------------------------
# Routes: Nurse (วินิจฉัย + จ่ายยา)
# --------------------------------------------------------------------------
@app.route("/nurse")
def nurse_queue():
    queue = query_db(
        """SELECT r.*, e.full_name, e.emp_code, e.department FROM requests r
           JOIN employees e ON e.id = r.employee_id
           WHERE r.status='approved' ORDER BY r.id"""
    )
    recent_visits = query_db(
        """SELECT v.*, r.id as request_id, e.full_name FROM visits v
           JOIN requests r ON r.id = v.request_id
           JOIN employees e ON e.id = r.employee_id
           ORDER BY v.id DESC LIMIT 10"""
    )
    return render_template("nurse_queue.html", queue=queue, recent_visits=recent_visits)


@app.route("/requests/<int:req_id>/diagnose", methods=["GET", "POST"])
def diagnose_form(req_id):
    req = query_db(
        """SELECT r.*, e.full_name, e.emp_code, e.department FROM requests r
           JOIN employees e ON e.id = r.employee_id WHERE r.id=?""",
        (req_id,),
        one=True,
    )
    if req is None:
        flash("ไม่พบคำขอนี้", "error")
        return redirect(url_for("nurse_queue"))
    if req["status"] != "approved":
        flash("คำขอนี้ยังไม่ได้รับการอนุมัติ หรือถูกบันทึกตรวจไปแล้ว", "error")
        return redirect(url_for("nurse_queue"))

    if request.method == "POST":
        nurse_name = request.form.get("nurse_name", "").strip()
        disease_group = request.form.get("disease_group", "").strip()
        diagnosis = request.form.get("diagnosis", "").strip()
        treatment_note = request.form.get("treatment_note", "").strip()
        medicine_ids = request.form.getlist("medicine_id[]")
        quantities = request.form.getlist("quantity[]")

        if not nurse_name or not disease_group or not diagnosis:
            flash("กรุณากรอกข้อมูลการตรวจให้ครบถ้วน", "error")
            return redirect(url_for("diagnose_form", req_id=req_id))

        # Validate stock availability before committing anything
        dispense_plan = []
        for med_id, qty in zip(medicine_ids, quantities):
            if not med_id or not qty:
                continue
            qty = int(qty)
            if qty <= 0:
                continue
            med = query_db("SELECT * FROM medicines WHERE id=?", (med_id,), one=True)
            if med is None:
                continue
            if med["stock_qty"] < qty:
                flash(f"ยา {med['name']} คงเหลือไม่เพียงพอ (คงเหลือ {med['stock_qty']} {med['unit']})", "error")
                return redirect(url_for("diagnose_form", req_id=req_id))
            dispense_plan.append((int(med_id), qty))

        visit_id = execute_db(
            """INSERT INTO visits (request_id, nurse_name, diagnosis, disease_group, treatment_note, visit_date)
               VALUES (?,?,?,?,?,?)""",
            (req_id, nurse_name, diagnosis, disease_group, treatment_note,
             datetime.now().strftime("%Y-%m-%d %H:%M")),
        )

        for med_id, qty in dispense_plan:
            execute_db(
                "INSERT INTO dispenses (visit_id, medicine_id, quantity) VALUES (?,?,?)",
                (visit_id, med_id, qty),
            )
            execute_db(
                "UPDATE medicines SET stock_qty = stock_qty - ? WHERE id=?", (qty, med_id)
            )

        execute_db("UPDATE requests SET status='completed' WHERE id=?", (req_id,))
        flash("บันทึกผลการตรวจและจ่ายยาเรียบร้อยแล้ว", "success")
        return redirect(url_for("nurse_queue"))

    medicines = query_db("SELECT * FROM medicines ORDER BY name")
    return render_template(
        "diagnose.html", req=req, medicines=medicines, disease_groups=DISEASE_GROUPS
    )


@app.route("/requests/<int:req_id>/visit")
def visit_detail(req_id):
    req = query_db(
        """SELECT r.*, e.full_name, e.emp_code, e.department FROM requests r
           JOIN employees e ON e.id = r.employee_id WHERE r.id=?""",
        (req_id,),
        one=True,
    )
    visit = query_db("SELECT * FROM visits WHERE request_id=?", (req_id,), one=True)
    dispenses = []
    if visit:
        dispenses = query_db(
            """SELECT m.name, m.unit, d.quantity FROM dispenses d
               JOIN medicines m ON m.id = d.medicine_id WHERE d.visit_id=?""",
            (visit["id"],),
        )
    if req is None or visit is None:
        flash("ไม่พบข้อมูลการตรวจ", "error")
        return redirect(url_for("nurse_queue"))
    return render_template("visit_detail.html", req=req, visit=visit, dispenses=dispenses)


# --------------------------------------------------------------------------
# Routes: Medicines / Stock
# --------------------------------------------------------------------------
@app.route("/medicines")
def list_medicines():
    medicines = query_db("SELECT * FROM medicines ORDER BY name")
    return render_template("medicines.html", medicines=medicines)


@app.route("/medicines/add", methods=["POST"])
def add_medicine():
    name = request.form.get("name", "").strip()
    unit = request.form.get("unit", "").strip()
    stock_qty = int(request.form.get("stock_qty") or 0)
    min_stock = int(request.form.get("min_stock") or 0)
    price = float(request.form.get("price") or 0)

    if not name or not unit:
        flash("กรุณากรอกชื่อยาและหน่วย", "error")
        return redirect(url_for("list_medicines"))

    execute_db(
        "INSERT INTO medicines (name, unit, stock_qty, min_stock, price) VALUES (?,?,?,?,?)",
        (name, unit, stock_qty, min_stock, price),
    )
    flash("เพิ่มรายการยาเรียบร้อยแล้ว", "success")
    return redirect(url_for("list_medicines"))


@app.route("/medicines/<int:med_id>/restock", methods=["POST"])
def restock_medicine(med_id):
    amount = int(request.form.get("amount") or 0)
    if amount > 0:
        execute_db("UPDATE medicines SET stock_qty = stock_qty + ? WHERE id=?", (amount, med_id))
        flash("เติมสต็อกยาเรียบร้อยแล้ว", "success")
    return redirect(url_for("list_medicines"))


# --------------------------------------------------------------------------
# Routes: Monthly analysis report
# --------------------------------------------------------------------------
@app.route("/reports/monthly")
def monthly_report():
    month = request.args.get("month") or date.today().strftime("%Y-%m")

    total_visits = query_db(
        "SELECT COUNT(*) c FROM visits WHERE strftime('%Y-%m', visit_date)=?", (month,), one=True
    )["c"]
    unique_employees = query_db(
        """SELECT COUNT(DISTINCT r.employee_id) c FROM visits v
           JOIN requests r ON r.id = v.request_id
           WHERE strftime('%Y-%m', v.visit_date)=?""",
        (month,),
        one=True,
    )["c"]

    disease_stats = query_db(
        """SELECT disease_group, COUNT(*) c FROM visits
           WHERE strftime('%Y-%m', visit_date)=?
           GROUP BY disease_group ORDER BY c DESC""",
        (month,),
    )
    medicine_stats = query_db(
        """SELECT m.name, m.unit, SUM(d.quantity) qty FROM dispenses d
           JOIN medicines m ON m.id = d.medicine_id
           JOIN visits v ON v.id = d.visit_id
           WHERE strftime('%Y-%m', v.visit_date)=?
           GROUP BY m.id ORDER BY qty DESC""",
        (month,),
    )

    top_disease = disease_stats[0]["disease_group"] if disease_stats else None
    top_medicine = medicine_stats[0]["name"] if medicine_stats else None

    return render_template(
        "report.html",
        month=month,
        total_visits=total_visits,
        unique_employees=unique_employees,
        disease_stats=disease_stats,
        medicine_stats=medicine_stats,
        top_disease=top_disease,
        top_medicine=top_medicine,
        disease_labels=[d["disease_group"] for d in disease_stats],
        disease_values=[d["c"] for d in disease_stats],
        med_labels=[m["name"] for m in medicine_stats],
        med_values=[m["qty"] for m in medicine_stats],
    )


# --------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
