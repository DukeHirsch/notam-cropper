import sys
import warnings

warnings.simplefilter(action='ignore', category=FutureWarning)
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

import os
import subprocess
import shutil
from datetime import datetime
import tkinter as tk
from tkinter import messagebox

# --- SETUP PATHS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(BASE_DIR, "backups")


class NotamLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("NOTAM-cropper | Local Control Panel")
        self.root.geometry("400x420")
        self.root.configure(bg="#263238")

        # --- HEADER ---
        tk.Label(root, text="LOCAL CONTROL PANEL", font=("Impact", 20), fg="#80CBC4", bg="#263238").pack(pady=30)

        # --- BUTTONS ---
        tk.Button(root, text="🛠️ RUN BLACKLIST MANAGER", bg="#FF9800", fg="white", font=("Arial", 12, "bold"),
                  command=self.run_blacklist).pack(fill=tk.X, padx=40, pady=10)

        tk.Button(root, text="🗃️ RUN CACHE MANAGER", bg="#2196F3", fg="white", font=("Arial", 12, "bold"),
                  command=self.run_cache_manager).pack(fill=tk.X, padx=40, pady=10)

        tk.Button(root, text="📦 RUN CONTEXT PACKAGER", bg="#009688", fg="white", font=("Arial", 12, "bold"),
                  command=self.run_packager).pack(fill=tk.X, padx=40, pady=10)

        tk.Button(root, text="💾 SAFE SAVE (BACKUP)", bg="#4CAF50", fg="white", font=("Arial", 12, "bold"),
                  command=self.run_safe_save).pack(fill=tk.X, padx=40, pady=10)

    def run_blacklist(self):
        script_path = os.path.join(BASE_DIR, "blacklist_manager.py")
        if os.path.exists(script_path):
            # Launches in a new Windows console so you can see the live print() statuses
            subprocess.Popen([sys.executable, script_path], creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            messagebox.showerror("Error", "blacklist_manager.py not found in root directory.")

    def run_cache_manager(self):
        script_path = os.path.join(BASE_DIR, "cache_manager.py")
        if os.path.exists(script_path):
            # Launches in a new Windows console, matching the Blacklist Manager behavior
            subprocess.Popen([sys.executable, script_path], creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            messagebox.showerror("Error", "cache_manager.py not found in root directory.")

    def run_packager(self):
        script_path = os.path.join(BASE_DIR, "context_packager.py")
        if os.path.exists(script_path):
            subprocess.Popen([sys.executable, script_path])
        else:
            messagebox.showerror("Error", "context_packager.py not found in root directory.")

    def run_safe_save(self):
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            new_backup_folder = os.path.join(BACKUP_ROOT, timestamp)

            # Target essential root files to safely snapshot project state
            files_to_backup = [f for f in os.listdir(BASE_DIR) if
                               f.endswith(('.py', '.txt', '.bat', '.gitignore', '.md'))]

            if not files_to_backup:
                messagebox.showwarning("Warning", "No files found to backup.")
                return

            os.makedirs(new_backup_folder, exist_ok=True)

            count = 0
            for filename in files_to_backup:
                source_path = os.path.join(BASE_DIR, filename)
                dest_path = os.path.join(new_backup_folder, filename)
                if os.path.isfile(source_path):
                    shutil.copy2(source_path, dest_path)
                    count += 1

            messagebox.showinfo("Success", f"Safe Save Complete!\n\nBacked up {count} files to:\nbackups\\{timestamp}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to perform Safe Save:\n{e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = NotamLauncher(root)
    root.mainloop()