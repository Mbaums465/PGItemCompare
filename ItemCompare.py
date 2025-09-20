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
            rarity TEXT,
            value INTEGER,
            PRIMARY KEY (character, timestamp, item_name)
        )
    ''')
    # Try to add missing columns if upgrading an older DB
    try:
        cursor.execute("ALTER TABLE inventories ADD COLUMN rarity TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE inventories ADD COLUMN value INTEGER")
    except sqlite3.OperationalError:
        pass
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
                            rarity = item.get("Rarity")
                            value = item.get("Value")
                            if name:
                                if name not in item_dict:
                                    item_dict[name] = {"qty": 0, "rarity": rarity, "value": value}
                                item_dict[name]["qty"] += stack
                        for name, info in item_dict.items():
                            cursor.execute(
                                "INSERT OR REPLACE INTO inventories VALUES (?, ?, ?, ?, ?, ?)",
                                (character, timestamp, name, info["qty"], info["rarity"], info["value"])
                            )
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
                    rarity = item.get("Rarity")
                    value = item.get("Value")
                    if name:
                        if name not in item_dict:
                            item_dict[name] = {"qty": 0, "rarity": rarity, "value": value}
                        item_dict[name]["qty"] += stack
                for name, info in item_dict.items():
                    cursor.execute(
                        "INSERT OR REPLACE INTO inventories VALUES (?, ?, ?, ?, ?, ?)",
                        (char, timestamp, name, info["qty"], info["rarity"], info["value"])
                    )
                conn.commit()
                return timestamp
    return None

def get_items_at_timestamp(conn, char, ts):
    cursor = conn.cursor()
    cursor.execute("SELECT item_name, quantity FROM inventories WHERE character=? AND timestamp=?", (char, ts))
    return {row[0]: row[1] for row in cursor.fetchall()}

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Project Gorgon Inventory Comparator")

        # Left frame for controls
        left_frame = tk.Frame(root)
        left_frame.grid(row=0, column=0, sticky="nw", padx=5, pady=2)

        self.folder = tk.StringVar(value=r"C:\Users\USER\AppData\LocalLow\Elder Game\Project Gorgon\Reports")
        tk.Label(left_frame, text="Folder:").grid(row=0, column=0, sticky="w", pady=1)
        tk.Entry(left_frame, textvariable=self.folder, width=50).grid(row=0, column=1, pady=1)
        tk.Button(left_frame, text="Browse", command=self.browse_folder).grid(row=0, column=2, pady=1)

        tk.Button(left_frame, text="Load Data", command=self.load_data).grid(row=1, column=0, columnspan=3, pady=1)

        tk.Label(left_frame, text="Character:").grid(row=2, column=0, sticky="w", pady=1)
        self.char_combo = ttk.Combobox(left_frame)
        self.char_combo.grid(row=2, column=1, pady=1)
        self.char_combo.bind("<<ComboboxSelected>>", self.update_ref_timestamps)

        tk.Label(left_frame, text="Reference Timestamp:").grid(row=3, column=0, sticky="w", pady=1)
        self.ref_ts_combo = ttk.Combobox(left_frame)
        self.ref_ts_combo.grid(row=3, column=1, pady=1)
        self.ref_ts_combo.bind("<<ComboboxSelected>>", self.update_comp_timestamps)

        tk.Label(left_frame, text="Compare To:").grid(row=4, column=0, sticky="w", pady=1)
        self.comp_ts_combo = ttk.Combobox(left_frame)
        self.comp_ts_combo.grid(row=4, column=1, pady=1)

        tk.Button(left_frame, text="Compare", command=self.compare).grid(row=5, column=0, columnspan=3, pady=1)

        self.time_diff = tk.Label(left_frame, text="")
        self.time_diff.grid(row=6, column=0, columnspan=3, pady=1)

        tk.Label(left_frame, text="Filter:").grid(row=7, column=0, sticky="w", pady=1)
        self.filter_entry = tk.Entry(left_frame)
        self.filter_entry.grid(row=7, column=1, pady=1)
        self.filter_entry.bind("<KeyRelease>", self.update_list)

        tk.Label(left_frame, text="View:").grid(row=8, column=0, sticky="w", pady=1)
        self.view_mode = tk.StringVar(value="Both")
        self.view_combo = ttk.Combobox(left_frame, textvariable=self.view_mode, values=["Both", "Gained", "Lost"])
        self.view_combo.grid(row=8, column=1, pady=1)
        self.view_combo.bind("<<ComboboxSelected>>", self.update_list)

        tk.Label(left_frame, text="Sort By:").grid(row=9, column=0, sticky="w", pady=1)
        self.sort_mode = tk.StringVar(value="Name")
        self.sort_combo = ttk.Combobox(left_frame, textvariable=self.sort_mode, values=["Name", "Change"])
        self.sort_combo.grid(row=9, column=1, pady=1)
        self.sort_combo.bind("<<ComboboxSelected>>", self.update_list)

        # Notebook for tabs
        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=0, column=1, rowspan=10, sticky="nsew", padx=5, pady=2)

        # Details tab
        details_frame = tk.Frame(self.notebook)
        self.notebook.add(details_frame, text="Details")

        self.results_tree = ttk.Treeview(details_frame, columns=("Item", "Change"), show="headings", height=20)
        self.results_tree.heading("Item", text="Item", command=lambda: self.treeview_sort_column(self.results_tree, "Item", False))
        self.results_tree.heading("Change", text="Change", command=lambda: self.treeview_sort_column(self.results_tree, "Change", False))
        self.results_tree.column("Item", width=400)
        self.results_tree.column("Change", width=100)
        self.results_tree.pack(fill="both", expand=True)

        self.results_tree.tag_configure("oddrow", background="#f0f0f0")
        self.results_tree.tag_configure("evenrow", background="#ffffff")
        self.results_tree.tag_configure("gained", foreground="green")
        self.results_tree.tag_configure("lost", foreground="red")

        style = ttk.Style()
        style.configure("Treeview", rowheight=25)
        style.configure("Treeview.Heading", font=("Arial", 12))

        # Summary tab
        summary_frame = tk.Frame(self.notebook)
        self.notebook.add(summary_frame, text="Summary")

        self.summary_text = tk.Text(summary_frame, height=20, width=60, font=("Arial", 12))
        self.summary_text.pack(fill="both", expand=True)

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
        self.prev_char = self.char_combo.get()
        self.prev_ref_ts = self.ref_ts_combo.get()
        load_json_files(self.folder.get(), self.conn)
        chars = get_characters(self.conn)
        self.char_combo['values'] = chars
        if chars:
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
        comp_dt = parse_timestamp(self.comp_ts)
        delta_time = comp_dt - ref_dt
        days = delta_time.days
        hours, remainder = divmod(delta_time.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        self.time_diff.config(text=f"Time between logs: {days} days, {hours} hours, {minutes} minutes")

        self.changes = changes
        self.update_list()

    def update_list(self, event=None):
        filter_text = self.filter_entry.get().lower()
        view = self.view_mode.get()
        sort = self.sort_mode.get()
        self.results_tree.delete(*self.results_tree.get_children())
        items = list(self.changes.items())
        if view == "Gained":
            items = [item for item in items if item[1] > 0]
        elif view == "Lost":
            items = [item for item in items if item[1] < 0]
        items = [item for item in items if filter_text in item[0].lower()]
        if sort == "Name":
            items.sort(key=lambda x: x[0])
        else:
            items.sort(key=lambda x: -abs(x[1]))
        for i, (name, delta) in enumerate(items):
            sign = "+" if delta > 0 else ""
            tag = "gained" if delta > 0 else "lost"
            row_tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.results_tree.insert("", "end", values=(name, f"{sign}{delta}"), tags=(tag, row_tag))
        self.update_summary()

    def update_summary(self):
        view = self.view_mode.get()
        self.summary_text.delete(1.0, tk.END)
        if not hasattr(self, 'changes'):
            return

        gained = {name: d for name, d in self.changes.items() if d > 0}
        lost = {name: -d for name, d in self.changes.items() if d < 0}

        cursor = self.conn.cursor()
        rarity_counts = {}
        rarity_values = {}
        misc_over_1k = 0
        misc_under_1k = 0
        misc_over_1k_value = 0
        misc_under_1k_value = 0
        phlogiston_prism_items = {}

        # Calculate totals for gained items
        for name, delta in gained.items():
            cursor.execute("SELECT rarity, value FROM inventories WHERE item_name=? ORDER BY timestamp DESC LIMIT 1", (name,))
            row = cursor.fetchone()
            rarity, value = (row if row else (None, None))

            # Check for Phlogiston or Prism items
            if "phlogiston" in name.lower() or "prism" in name.lower():
                phlogiston_prism_items[name] = delta

            if rarity:
                rarity_counts[rarity] = rarity_counts.get(rarity, 0) + delta
                if value is not None:
                    rarity_values[rarity] = rarity_values.get(rarity, 0) + (value * delta)
            elif value is not None:
                if value >= 1000:
                    misc_over_1k += delta
                    misc_over_1k_value += value * delta
                else:
                    misc_under_1k += delta
                    misc_under_1k_value += value * delta

        # Check lost items for Phlogiston/Prism
        for name, delta in lost.items():
            if "phlogiston" in name.lower() or "prism" in name.lower():
                if name in phlogiston_prism_items:
                    phlogiston_prism_items[name] -= delta
                else:
                    phlogiston_prism_items[name] = -delta

        total_gained = sum(gained.values())
        total_lost = sum(lost.values())

        # Display overall totals
        if view in ["Both", "Gained"] and total_gained > 0:
            self.summary_text.insert(tk.END, f"Overall Gained: +{total_gained}\n")
        
        if view in ["Both", "Lost"] and total_lost > 0:
            self.summary_text.insert(tk.END, f"Overall Lost: -{total_lost}\n")

        # Phlogiston and Prism items section
        if phlogiston_prism_items:
            self.summary_text.insert(tk.END, "\nPhlogiston & Prism Items:\n")
            for item_name, change in sorted(phlogiston_prism_items.items()):
                if change != 0:
                    sign = "+" if change > 0 else ""
                    self.summary_text.insert(tk.END, f"  {item_name}: {sign}{change}\n")

        # Rarity breakdown with values
        if rarity_counts:
            self.summary_text.insert(tk.END, "\nRarity Breakdown:\n")
            for rarity in sorted(rarity_counts.keys()):
                count = rarity_counts[rarity]
                value = rarity_values.get(rarity, 0)
                if value > 0:
                    self.summary_text.insert(tk.END, f"  {rarity} Gear: +{count} | Value: {value:,}\n")
                else:
                    self.summary_text.insert(tk.END, f"  {rarity} Gear: +{count}\n")

        # Misc breakdown with values
        if misc_over_1k or misc_under_1k:
            self.summary_text.insert(tk.END, "\nMisc Items:\n")
            if misc_over_1k:
                self.summary_text.insert(tk.END, f"  Misc over 1k: +{misc_over_1k} | Value: {misc_over_1k_value:,}\n")
            if misc_under_1k:
                self.summary_text.insert(tk.END, f"  Misc under 1k: +{misc_under_1k} | Value: {misc_under_1k_value:,}\n")

        # Total value summary
        total_category_value = sum(rarity_values.values()) + misc_over_1k_value + misc_under_1k_value
        if total_category_value > 0:
            self.summary_text.insert(tk.END, f"\nTotal Value of All Categories: {total_category_value:,}\n")

    def treeview_sort_column(self, tv, col, reverse):
        items = [(tv.set(k, col), k) for k in tv.get_children('')]
        try:
            items.sort(key=lambda t: int(t[0]), reverse=reverse)
        except ValueError:
            items.sort(reverse=reverse)
        for index, (val, k) in enumerate(items):
            tv.move(k, '', index)
        tv.heading(col, command=lambda: self.treeview_sort_column(tv, col, not reverse))

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
