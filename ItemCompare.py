import os
import json
import sqlite3
import tkinter as tk
from tkinter import filedialog, ttk
from datetime import datetime, timedelta
import re

DB_FILE = "inventory.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventories (
            character TEXT,
            timestamp TEXT,
            item_name TEXT,
            quantity INTEGER,
            PRIMARY KEY (character, timestamp, item_name)
        )
    ''')
    conn.commit()
    return conn

def parse_timestamp(ts_str):
    try:
        return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%SZ")
    except ValueError:
        return None

def parse_filename_date(filename):
    match = re.search(r'(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}Z)', filename)
    if match:
        date_str = match.group(1)
        try:
            return datetime.strptime(date_str, "%Y-%m-%d-%H-%M-%SZ")
        except ValueError:
            return None
    return None

def load_json_files(folder, conn):
    cursor = conn.cursor()
    for filename in os.listdir(folder):
        if filename.endswith(".json") and "_items_" in filename:
            filepath = os.path.join(folder, filename)
            with open(filepath, 'r') as f:
                try:
                    data = json.load(f)
                    character = data.get("Character")
                    timestamp = data.get("Timestamp")
                    if character and timestamp:
                        cursor.execute("SELECT COUNT(*) FROM inventories WHERE character=? AND timestamp=?", (character, timestamp))
                        if cursor.fetchone()[0] > 0:
                            continue
                        item_dict = {}
                        for item in data.get("Items", []):
                            name = item.get("Name")
                            stack = item.get("StackSize", 1)
                            if name:
                                item_dict[name] = item_dict.get(name, 0) + stack
                        for name, qty in item_dict.items():
                            cursor.execute("INSERT OR REPLACE INTO inventories VALUES (?, ?, ?, ?)", (character, timestamp, name, qty))
                        conn.commit()
                except json.JSONDecodeError:
                    pass

def get_characters(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT character FROM inventories ORDER BY character")
    return [row[0] for row in cursor.fetchall()]

def get_timestamps_for_char(conn, char):
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT timestamp FROM inventories WHERE character=? ORDER BY timestamp DESC", (char,))
    return [row[0] for row in cursor.fetchall()]

def get_latest_file_for_char(folder, char):
    latest_file = None
    latest_date = None
    for filename in os.listdir(folder):
        if filename.startswith(f"{char}_items_") and filename.endswith(".json"):
            file_date = parse_filename_date(filename)
            if file_date and (not latest_date or file_date > latest_date):
                latest_date = file_date
                latest_file = os.path.join(folder, filename)
    return latest_file

def load_latest_if_new(folder, conn, char):
    latest_file = get_latest_file_for_char(folder, char)
    if latest_file:
        with open(latest_file, 'r') as f:
            data = json.load(f)
            timestamp = data.get("Timestamp")
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM inventories WHERE character=? AND timestamp=?", (char, timestamp))
            if cursor.fetchone()[0] == 0:
                item_dict = {}
                for item in data.get("Items", []):
                    name = item.get("Name")
                    stack = item.get("StackSize", 1)
                    if name:
                        item_dict[name] = item_dict.get(name, 0) + stack
                for name, qty in item_dict.items():
                    cursor.execute("INSERT OR REPLACE INTO inventories VALUES (?, ?, ?, ?)", (char, timestamp, name, qty))
                conn.commit()
                return timestamp
    return None

def get_items_at_timestamp(conn, char, ts):
    cursor = conn.cursor()
    cursor.execute("SELECT item_name, quantity FROM inventories WHERE character=? AND timestamp=?", (char, ts))
    return dict(cursor.fetchall())

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Project Gorgon Inventory Comparator")

        self.folder = tk.StringVar(value=r"C:\Users\USER\AppData\LocalLow\Elder Game\Project Gorgon\Reports")
        tk.Label(root, text="Folder:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        tk.Entry(root, textvariable=self.folder, width=50).grid(row=0, column=1, padx=5, pady=5)
        tk.Button(root, text="Browse", command=self.browse_folder).grid(row=0, column=2, padx=5, pady=5)

        tk.Button(root, text="Load Data", command=self.load_data).grid(row=1, column=0, columnspan=3, pady=5)

        self.char_label = tk.Label(root, text="Character:")
        self.char_label.grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.char_combo = ttk.Combobox(root)
        self.char_combo.grid(row=2, column=1, padx=5, pady=5)
        self.char_combo.bind("<<ComboboxSelected>>", self.update_ref_timestamps)

        self.ref_ts_label = tk.Label(root, text="Reference Timestamp:")
        self.ref_ts_label.grid(row=3, column=0, sticky="w", padx=5, pady=5)
        self.ref_ts_combo = ttk.Combobox(root)
        self.ref_ts_combo.grid(row=3, column=1, padx=5, pady=5)
        self.ref_ts_combo.bind("<<ComboboxSelected>>", self.update_comp_timestamps)

        self.comp_ts_label = tk.Label(root, text="Compare To:")
        self.comp_ts_label.grid(row=4, column=0, sticky="w", padx=5, pady=5)
        self.comp_ts_combo = ttk.Combobox(root)
        self.comp_ts_combo.grid(row=4, column=1, padx=5, pady=5)

        tk.Button(root, text="Compare", command=self.compare).grid(row=5, column=0, columnspan=3, pady=5)

        self.time_diff = tk.Label(root, text="")
        self.time_diff.grid(row=6, column=0, columnspan=3, pady=5)

        tk.Label(root, text="Filter:").grid(row=7, column=0, sticky="w", padx=5, pady=5)
        self.filter_entry = tk.Entry(root)
        self.filter_entry.grid(row=7, column=1, padx=5, pady=5)
        self.filter_entry.bind("<KeyRelease>", self.update_list)

        tk.Label(root, text="View:").grid(row=7, column=2, sticky="w", padx=5, pady=5)
        self.view_mode = tk.StringVar(value="Both")
        self.view_combo = ttk.Combobox(root, textvariable=self.view_mode, values=["Both", "Gained", "Lost"])
        self.view_combo.grid(row=7, column=3, padx=5, pady=5)
        self.view_combo.bind("<<ComboboxSelected>>", self.update_list)

        # Use Treeview for results with grid lines and alternating colors
        self.results_tree = ttk.Treeview(root, columns=("Item", "Change"), show="headings", height=20)
        self.results_tree.heading("Item", text="Item")
        self.results_tree.heading("Change", text="Change")
        self.results_tree.column("Item", width=400)
        self.results_tree.column("Change", width=100)
        self.results_tree.grid(row=8, column=0, columnspan=4, padx=5, pady=5)

        # Add alternating background colors
        self.results_tree.tag_configure("oddrow", background="#f0f0f0")
        self.results_tree.tag_configure("evenrow", background="#ffffff")
        self.results_tree.tag_configure("gained", foreground="green")
        self.results_tree.tag_configure("lost", foreground="red")

        # Add grid lines
        style = ttk.Style()
        style.configure("Treeview", rowheight=25)
        style.configure("Treeview.Heading", font=("Arial", 12))

        self.conn = init_db()
        self.timestamps = {}
        self.ref_ts = None
        self.comp_ts = None
        self.prev_char = None
        self.prev_ref_ts = None

    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder.get())
        if folder:
            self.folder.set(folder)

    def load_data(self):
        # Store previous selections
        self.prev_char = self.char_combo.get()
        self.prev_ref_ts = self.ref_ts_combo.get()
        load_json_files(self.folder.get(), self.conn)
        chars = get_characters(self.conn)
        self.char_combo['values'] = chars
        if chars:
            # Restore previous character or set to first
            if self.prev_char in chars:
                self.char_combo.set(self.prev_char)
            else:
                self.char_combo.set(chars[0])
            self.update_ref_timestamps()

    def update_ref_timestamps(self, event=None):
        char = self.char_combo.get()
        if char:
            ts_list = get_timestamps_for_char(self.conn, char)
            self.timestamps[char] = ts_list
            self.ref_ts_combo['values'] = ts_list
            if ts_list:
                # Restore previous timestamp or set to latest
                if self.prev_ref_ts in ts_list:
                    self.ref_ts_combo.set(self.prev_ref_ts)
                else:
                    self.ref_ts_combo.set(ts_list[0])
                self.update_comp_timestamps()

    def update_comp_timestamps(self, event=None):
        char = self.char_combo.get()
        ref_ts = self.ref_ts_combo.get()
        if char and ref_ts:
            all_ts = self.timestamps.get(char, [])
            ref_dt = parse_timestamp(ref_ts)
            later_ts = [ts for ts in all_ts if parse_timestamp(ts) > ref_dt]
            later_ts = sorted(later_ts, key=parse_timestamp, reverse=True)
            later_ts.insert(0, "Latest")
            self.comp_ts_combo['values'] = later_ts
            if later_ts:
                self.comp_ts_combo.set(later_ts[0])

    def compare(self):
        char = self.char_combo.get()
        self.ref_ts = self.ref_ts_combo.get()
        comp_sel = self.comp_ts_combo.get()

        if comp_sel == "Latest":
            new_ts = load_latest_if_new(self.folder.get(), self.conn, char)
            if new_ts:
                self.prev_char = char
                self.prev_ref_ts = self.ref_ts
                self.update_ref_timestamps()
                self.comp_ts = new_ts
            else:
                all_ts = self.timestamps.get(char, [])
                if all_ts:
                    self.comp_ts = max(all_ts, key=parse_timestamp)
                else:
                    self.comp_ts = None
        else:
            self.comp_ts = comp_sel

        if not self.ref_ts or not self.comp_ts:
            return

        ref_items = get_items_at_timestamp(self.conn, char, self.ref_ts)
        comp_items = get_items_at_timestamp(self.conn, char, self.comp_ts)

        changes = {}
        all_names = set(ref_items.keys()) | set(comp_items.keys())
        for name in all_names:
            ref_qty = ref_items.get(name, 0)
            comp_qty = comp_items.get(name, 0)
            delta = comp_qty - ref_qty
            if delta != 0:
                changes[name] = delta

        ref_dt = parse_timestamp(self.ref_ts)