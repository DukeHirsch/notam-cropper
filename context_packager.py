import os
import tkinter as tk
from tkinter import messagebox, Listbox, Scrollbar, filedialog
import subprocess
import time
from datetime import datetime
import sys
import warnings
import shutil

# --- WINDOWS SAFETY & STANDARDS ---
warnings.simplefilter(action='ignore', category=FutureWarning)
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

# --- SMART CONFIGURATION ---
# Assumes this script sits in the root of NOTAM-cropper
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
TEMP_PATH = os.path.join(BASE_PATH, "Temp")
BACKUP_ROOT = os.path.join(BASE_PATH, "backups")

# --- SAFETY FILTERS ---
IGNORE_FOLDERS = {
    "__pycache__", ".git", ".idea", ".venv", "venv", "node_modules",
    "backups", "Temp", "External Libraries", "Scratches and Consoles"
}

# Files to list but NEVER read content (Security/Binary)
SENSITIVE_OR_BINARY = {
    "secrets.toml", "gemini_key.txt", ".DS_Store",
    ".mp4", ".mp3", ".png", ".jpg", ".jpeg", ".exe", ".dll", ".zip",
    ".pdf", ".wav", ".pyc", ".pkl", ".pickle", ".db", ".sqlite"
}


class ContextPackager:
    def __init__(self, root):
        self.root = root
        self.root.title("NOTAM-cropper | Context Packager")
        self.root.geometry("600x800")
        self.root.configure(bg="#263238")

        if not os.path.exists(TEMP_PATH): os.makedirs(TEMP_PATH)
        self.clear_temp(silent=True)

        # --- HEADER ---
        tk.Label(root, text="CONTEXT & TIME MACHINE", font=("Impact", 20), fg="#80CBC4", bg="#263238").pack(pady=10)
        tk.Label(root, text=f"Scanning Root: {BASE_PATH}", font=("Arial", 8), fg="#546E7A", bg="#263238").pack(pady=0)

        # --- SECTION 1: LIVE CONTEXT ---
        frame_live = tk.LabelFrame(root, text=" 1. LIVE CONTEXT TOOLS ", font=("Arial", 10, "bold"),
                                   bg="#263238", fg="white", padx=10, pady=10)
        frame_live.pack(fill=tk.X, padx=15, pady=5)

        # ROW 1: Quick Actions
        row_a = tk.Frame(frame_live, bg="#263238")
        row_a.pack(fill=tk.X, pady=5)

        tk.Button(row_a, text="📸 SNAPSHOT", bg="#546E7A", fg="white", command=self.take_snapshot).pack(
            side=tk.LEFT, padx=5)

        # Standard Bundle (Modified for Streamlit App)
        tk.Button(row_a, text="📦 BUNDLE PROJECT (Code & Configs)", bg="#009688", fg="white", font=("Arial", 10, "bold"),
                  command=self.pack_context).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # ROW 2: Detailed Scans
        row_b = tk.Frame(frame_live, bg="#263238")
        row_b.pack(fill=tk.X, pady=5)

        # Scan Root Detailed
        tk.Button(row_b, text="📂 SCAN ROOT (Detailed)", bg="#FF9800", fg="white", font=("Arial", 10, "bold"),
                  command=self.scan_root_detailed).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Custom Folder Scan
        tk.Button(row_b, text="📁 SCAN SPECIFIC...", bg="#7E57C2", fg="white", font=("Arial", 10, "bold"),
                  command=self.scan_specific_folder).pack(side=tk.LEFT, padx=5)

        # --- SECTION 2: BACKUPS ---
        frame_backup = tk.LabelFrame(root, text=" 2. BACKUP TIME MACHINE ", font=("Arial", 10, "bold"),
                                     bg="#263238", fg="#FFAB40", padx=10, pady=10)
        frame_backup.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        cols = tk.Frame(frame_backup, bg="#263238")
        cols.pack(fill=tk.BOTH, expand=True)

        col1 = tk.Frame(cols, bg="#263238")
        col1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        self.list_backups = Listbox(col1, height=10, bg="#37474F", fg="white", selectmode=tk.SINGLE)
        self.list_backups.pack(fill=tk.BOTH, expand=True)
        self.list_backups.bind('<<ListboxSelect>>', self.on_backup_select)

        col2 = tk.Frame(cols, bg="#263238")
        col2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        self.list_files = Listbox(col2, height=10, bg="#37474F", fg="white", selectmode=tk.MULTIPLE)
        self.list_files.pack(fill=tk.BOTH, expand=True)

        self.btn_fetch = tk.Button(frame_backup, text="⏪ COPY SELECTED OLD FILES",
                                   bg="#FF6F00", fg="white", font=("Arial", 11, "bold"),
                                   state=tk.DISABLED, command=self.pack_backup_files)
        self.btn_fetch.pack(fill=tk.X, pady=(10, 5))

        self.btn_milestone = tk.Button(frame_backup, text="💾 CREATE MILESTONE BACKUP",
                                       bg="#4CAF50", fg="white", font=("Arial", 11, "bold"),
                                       command=self.create_milestone_backup)
        self.btn_milestone.pack(fill=tk.X, pady=(5, 10))

        # Only refresh list on launch, no more auto-saving
        self.refresh_backups()

    # --- UTILS ---
    def clear_temp(self, silent=False):
        try:
            for f in os.listdir(TEMP_PATH):
                try:
                    os.remove(os.path.join(TEMP_PATH, f))
                except:
                    pass
            if not silent: messagebox.showinfo("Cleared", "Temp folder wiped clean.")
        except:
            pass

    def take_snapshot(self):
        try:
            from PIL import ImageGrab
        except:
            messagebox.showerror("Error", "Missing Pillow library. (pip install Pillow)");
            return
        self.root.iconify()
        time.sleep(0.5)
        try:
            ts = datetime.now().strftime("%H-%M-%S")
            fp = os.path.join(TEMP_PATH, f"Screen_{ts}.png")
            ImageGrab.grab().save(fp)
            self.root.deiconify()
            messagebox.showinfo("Snapped", f"Saved: {fp}")
        except Exception as e:
            self.root.deiconify()
            messagebox.showerror("Error", str(e))

    def get_pip_libraries(self):
        try:
            return f"--- INSTALLED LIBS ---\n{subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], encoding='utf-8')}\n"
        except:
            return ""

    # --- INTEGRATED BACKUP LOGIC FOR NOTAM CROPPER ---
    def create_milestone_backup(self):
        """Manually backs up key project files when a milestone is reached."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        new_backup_folder = os.path.join(BACKUP_ROOT, timestamp)

        files_to_backup = [f for f in os.listdir(BASE_PATH) if f.endswith(('.py', '.txt', '.bat', '.gitignore', '.toml', '.md'))]

        if not files_to_backup:
            messagebox.showwarning("Warning", "No files found to backup.")
            return

        if not os.path.exists(new_backup_folder):
            os.makedirs(new_backup_folder)

        count = 0
        for filename in files_to_backup:
            source_path = os.path.join(BASE_PATH, filename)
            dest_path = os.path.join(new_backup_folder, filename)
            try:
                shutil.copy2(source_path, dest_path)
                count += 1
            except:
                pass

        if count == 0:
            os.rmdir(new_backup_folder)
            messagebox.showwarning("Warning", "Backup failed. No files were copied.")
        else:
            self.manage_rotation()
            self.refresh_backups()
            messagebox.showinfo("Success", f"Milestone Backup created!\nSaved {count} files to:\n{timestamp}")

    def manage_rotation(self, max_backups=5):
        if not os.path.exists(BACKUP_ROOT): return
        all_backups = sorted([f for f in os.listdir(BACKUP_ROOT) if os.path.isdir(os.path.join(BACKUP_ROOT, f))])

        if len(all_backups) > max_backups:
            excess = len(all_backups) - max_backups
            for i in range(excess):
                try:
                    shutil.rmtree(os.path.join(BACKUP_ROOT, all_backups[i]))
                except:
                    pass

    # --- SCANNING LOGIC ---
    def generate_folder_dump(self, target_folder, is_full_project=False):
        tree_str = f"--- FOLDER STRUCTURE: {os.path.basename(target_folder)} ---\n"
        content_str = ""

        for root, dirs, files in os.walk(target_folder):
            dirs[:] = [d for d in dirs if d not in IGNORE_FOLDERS]

            rel_path = os.path.relpath(root, target_folder)
            indent = '    ' * (rel_path.count(os.sep) + 1)

            if rel_path != ".": tree_str += f"{indent}{os.path.basename(root)}/\n"

            for f in files:
                if f == ".DS_Store": continue
                tree_str += f"{indent}    {f}\n"

                # If bundling the project, only grab relevant scripts and requirements
                if is_full_project:
                    if not f.endswith((".py", ".bat", ".txt", ".toml", ".gitignore", ".md")):
                        continue

                full_path = os.path.join(root, f)
                display_path = os.path.relpath(full_path, BASE_PATH)

                content_str += f"\n\n--- FILE: {display_path} ---\n"

                # SECURITY CHECK
                _, ext = os.path.splitext(f)
                if f in SENSITIVE_OR_BINARY or ext.lower() in SENSITIVE_OR_BINARY:
                    content_str += "[CONTENT HIDDEN: SENSITIVE OR BINARY]\n"
                else:
                    try:
                        with open(full_path, "r", encoding="utf-8") as file:
                            content_str += file.read()
                    except:
                        content_str += "[READ ERROR / BINARY]"

        return tree_str + "\n" + content_str

    def pack_context(self):
        dump = "Here is my CURRENT PROJECT STATE for NOTAM-cropper:\n\n"
        dump += self.get_pip_libraries()
        dump += self.generate_folder_dump(BASE_PATH, is_full_project=True)

        self.root.clipboard_clear()
        self.root.clipboard_append(dump)
        self.root.update()
        messagebox.showinfo("Copied", "✅ Project bundled! (Code, Bats, & Configs copied to clipboard)")

    def scan_root_detailed(self):
        dump = f"Here is a DETAILED scan of the ROOT folder:\n\n"
        dump += self.generate_folder_dump(BASE_PATH, is_full_project=False)

        self.root.clipboard_clear()
        self.root.clipboard_append(dump)
        self.root.update()
        messagebox.showinfo("Scanned", "✅ Detailed Root Scan Copied!")

    def scan_specific_folder(self):
        target_dir = filedialog.askdirectory(initialdir=BASE_PATH, title="Select Folder")
        if not target_dir: return
        dump = self.generate_folder_dump(target_dir, is_full_project=False)
        self.root.clipboard_clear()
        self.root.clipboard_append(dump)
        self.root.update()
        messagebox.showinfo("Scanned", "✅ Folder scanned safely!")

    # --- TIME MACHINE LOGIC ---
    def refresh_backups(self):
        self.list_backups.delete(0, tk.END)
        if not os.path.exists(BACKUP_ROOT): return
        backups = sorted([d for d in os.listdir(BACKUP_ROOT) if os.path.isdir(os.path.join(BACKUP_ROOT, d))],
                         reverse=True)
        for b in backups: self.list_backups.insert(tk.END, b)

    def on_backup_select(self, event):
        selection = self.list_backups.curselection()
        if not selection: return
        folder_name = self.list_backups.get(selection[0])
        full_path = os.path.join(BACKUP_ROOT, folder_name)
        self.list_files.delete(0, tk.END)

        files = [f for f in os.listdir(full_path) if os.path.isfile(os.path.join(full_path, f))]
        for f in files: self.list_files.insert(tk.END, f)
        self.btn_fetch.config(state=tk.NORMAL)

    def pack_backup_files(self):
        b_idx = self.list_backups.curselection()
        if not b_idx: return
        folder_name = self.list_backups.get(b_idx[0])
        folder_path = os.path.join(BACKUP_ROOT, folder_name)
        f_idxs = self.list_files.curselection()
        if not f_idxs: return

        dump = f"🚨 RESTORE FROM BACKUP: {folder_name}\n\n"
        count = 0
        for idx in f_idxs:
            filename = self.list_files.get(idx)
            dump += f"\n--- BACKUP FILE: {filename} ---\n"
            with open(os.path.join(folder_path, filename), "r", encoding="utf-8") as f: dump += f.read()
            count += 1

        self.root.clipboard_clear()
        self.root.clipboard_append(dump)
        self.root.update()
        messagebox.showinfo("Time Machine", f"✅ Copied {count} files to clipboard!")


if __name__ == "__main__":
    root = tk.Tk()
    app = ContextPackager(root)
    root.mainloop()

    if __name__ == '__main__':
        import sys
        from streamlit.web import cli as stcli

        sys.argv = ["streamlit", "run", sys.argv[0]]
        sys.exit(stcli.main())