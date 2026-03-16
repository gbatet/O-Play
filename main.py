import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from PIL import Image, ImageTk
import gpxpy
import numpy as np
import json
import os
from datetime import datetime
from geopy.distance import geodesic


class OrienteeringAnalyser:
    def __init__(self, root):
        self.root = root
        self.root.title("O-Play: Orienteering Analysis")

        # Initial State Setup
        self.reset_state()
        self.setup_ui()

    def reset_state(self):
        """Resets all session-specific data for a clean workflow."""
        self.map_path = ""
        self.original_map = None
        self.display_photo = None
        self.zoom_level = 1.0
        self.is_playing = False

        self.ref_pixels = []
        self.ref_coords = []
        self.track_pts = []
        self.track_distances = []
        self.start_time = None
        self.last_split_time = None
        self.last_split_idx = 0
        self.split_counter = 1
        self.M = None

        # Reset UI elements if they exist
        if hasattr(self, 'canvas'):
            self.canvas.delete("all")
        if hasattr(self, 'splits_list'):
            self.splits_list.delete("1.0", tk.END)
        if hasattr(self, 'time_label'):
            self.time_label.config(text="00:00:00")
        if hasattr(self, 'dist_label'):
            self.dist_label.config(text="0.00 km")
        if hasattr(self, 'slider'):
            self.slider.set(0)
            self.slider.config(to=100)

    def setup_ui(self):
        toolbar = tk.Frame(self.root, bg="#f0f0f0", bd=1, relief=tk.RAISED)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        tk.Button(toolbar, text="INFO", command=self.info).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(toolbar, text="1. Load Map", command=self.load_map).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(toolbar, text="2. Load Cal", command=self.load_calibration).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="3. Load GPX", command=self.load_gpx).pack(side=tk.LEFT, padx=5)
        tk.Button(toolbar, text="Save Cal", command=self.save_calibration).pack(side=tk.LEFT, padx=2)

        tk.Label(toolbar, text="Zoom:", bg="#f0f0f0").pack(side=tk.LEFT, padx=(10, 0))
        tk.Button(toolbar, text="+", width=2, command=lambda: self.change_zoom(1.1)).pack(side=tk.LEFT)
        tk.Button(toolbar, text="-", width=2, command=lambda: self.change_zoom(0.9)).pack(side=tk.LEFT)

        self.play_btn = tk.Button(toolbar, text="Play", width=6, command=self.toggle_play)
        self.play_btn.pack(side=tk.LEFT, padx=10)

        self.time_label = tk.Label(toolbar, text="00:00:00", font=('Courier', 12, 'bold'), bg="black", fg="lime")
        self.time_label.pack(side=tk.LEFT, padx=5)

        self.dist_label = tk.Label(toolbar, text="0.00 km", font=('Courier', 12, 'bold'), bg="black", fg="#00e5ff")
        self.dist_label.pack(side=tk.LEFT, padx=5)

        tk.Button(toolbar, text="RECORD SPLIT", bg="orange", font=('Arial', 9, 'bold'), command=self.record_split).pack(
            side=tk.LEFT, padx=5)

        tk.Label(toolbar, text="Delay:", bg="#f0f0f0").pack(side=tk.LEFT, padx=(10, 2))
        self.speed_var = tk.IntVar(value=500)
        self.speed_scale = tk.Scale(toolbar, from_=10, to=1000, orient=tk.HORIZONTAL,
                                    variable=self.speed_var, showvalue=False, width=10,
                                    command=lambda e: self.update_delay_label())
        self.speed_scale.pack(side=tk.LEFT)

        self.delay_info = tk.Label(toolbar, text="500 ms", bg="#f0f0f0", font=('Arial', 8, 'italic'))
        self.delay_info.pack(side=tk.LEFT, padx=2)

        self.slider = tk.Scale(self.root, from_=0, to=100, orient=tk.HORIZONTAL, command=self.update_plot)
        self.slider.pack(side=tk.TOP, fill=tk.X, padx=10)

        main_area = tk.Frame(self.root)
        main_area.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.splits_panel = tk.Frame(main_area, width=280, bg="#e0e0e0")
        self.splits_panel.pack(side=tk.RIGHT, fill=tk.Y)
        tk.Label(self.splits_panel, text="SPLITS LOG", font=('Arial', 10, 'bold')).pack(pady=5)
        self.splits_list = tk.Text(self.splits_panel, width=35, font=('Courier', 8))
        self.splits_list.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)
        tk.Button(self.splits_panel, text="Clear Log", command=self.clear_splits).pack(pady=5)

        self.map_container = tk.Frame(main_area)
        self.map_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.v_scroll = tk.Scrollbar(self.map_container, orient=tk.VERTICAL)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.h_scroll = tk.Scrollbar(self.map_container, orient=tk.HORIZONTAL)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        self.canvas = tk.Canvas(self.map_container, bg="gray",
                                xscrollcommand=self.h_scroll.set,
                                yscrollcommand=self.v_scroll.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.v_scroll.config(command=self.canvas.yview)
        self.h_scroll.config(command=self.canvas.xview)

        self.canvas.bind("<Button-1>", self.on_map_click)
        self.canvas.bind("<ButtonPress-3>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B3-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))

    def update_delay_label(self):
        self.delay_info.config(text=f"{self.speed_var.get()} ms")

    def format_seconds(self, seconds):
        h, m, s = int(seconds // 3600), int((seconds % 3600) // 60), int(seconds % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def record_split(self):
        if not self.track_pts: return
        idx = self.slider.get()
        p_now = self.track_pts[idx]

        overall_sec = (p_now['time'] - self.start_time).total_seconds()
        split_sec = (p_now['time'] - self.last_split_time).total_seconds()

        dist_total = self.track_distances[idx]
        dist_last_split = self.track_distances[self.last_split_idx]
        dist_diff = dist_total - dist_last_split

        if dist_diff > 0 and split_sec > 0:
            pace_min_km = (split_sec / 60) / dist_diff
            pace_str = f"{int(pace_min_km)}:{int((pace_min_km % 1) * 60):02d} min/km"
        else:
            pace_str = "--:--"

        entry = f"S{self.split_counter} | Tot: {self.format_seconds(overall_sec)} ({dist_total:.2f}km)\n    Split: {self.format_seconds(split_sec)} ({pace_str})\n{'-' * 28}\n"

        self.splits_list.insert(tk.END, entry)
        self.splits_list.see(tk.END)

        self.last_split_time = p_now['time']
        self.last_split_idx = idx
        self.split_counter += 1

    def clear_splits(self):
        self.splits_list.delete("1.0", tk.END)
        self.split_counter = 1
        if self.start_time:
            self.last_split_time = self.start_time
            self.last_split_idx = 0

    def load_calibration(self):
        path = filedialog.askopenfilename(filetypes=[("Text", "*.txt")])
        if not path: return
        try:
            with open(path, 'r', encoding="utf-8") as f:
                data = json.load(f)

            cal_dir = os.path.dirname(path)
            map_filename = data["map_filename"]
            full_map_path = os.path.join(cal_dir, map_filename)

            if not os.path.exists(full_map_path):
                messagebox.showerror("Error",
                                     f"Image file '{map_filename}' not found in the same folder as the calibration file.")
                return

            # Reset state before applying calibration, but keep the new path
            self.reset_state()
            self.map_path = full_map_path
            self.original_map = Image.open(self.map_path)
            self.ref_coords = data["coords"]
            self.ref_pixels = [[p[0] * self.zoom_level, p[1] * self.zoom_level] for p in data["pixels"]]
            self.calculate_mapping()
            self.render_map()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load: {e}")

    def info(self):
        messagebox.showinfo("INFO", "1. First load a map image.\n2.0. If no calibration file exist, click on 3 points and set the coordinates. Save cal on *.txt file\n2.1. If calibration exist load cal file.\n3. Load GPX file to analyse\n ")

    def save_calibration(self):
        if not self.map_path or len(self.ref_pixels) < 3:
            messagebox.showwarning("Warning", "Load a map and calibrate 3 points first.")
            return

        data = {
            "map_filename": os.path.basename(self.map_path),
            "pixels": [[p[0] / self.zoom_level, p[1] / self.zoom_level] for p in self.ref_pixels],
            "coords": self.ref_coords
        }
        path = filedialog.asksaveasfilename(defaultextension=".txt")
        if path:
            with open(path, 'w', encoding="utf-8") as f:
                json.dump(data, f)

    def load_map(self):
        path = filedialog.askopenfilename(filetypes=[("Image", ".jpg .jpeg .png")])
        if path:
            # Trigger reset for a new workflow
            self.reset_state()
            self.map_path = path
            self.original_map = Image.open(path)
            messagebox.showinfo("Calibrate", "Click on 3 points and set coordinates or Load calibration file")
            self.render_map()

    def render_map(self):
        if not self.original_map: return
        w, h = self.original_map.size
        new_size = (int(w * self.zoom_level), int(h * self.zoom_level))
        self.display_photo = ImageTk.PhotoImage(self.original_map.resize(new_size, Image.Resampling.LANCZOS))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.display_photo)
        self.canvas.config(scrollregion=(0, 0, new_size[0], new_size[1]))
        for p in self.ref_pixels:
            self.canvas.create_oval(p[0] - 5, p[1] - 5, p[0] + 5, p[1] + 5, fill="red", tags="ref")
        self.update_plot(self.slider.get())

    def change_zoom(self, factor):
        self.zoom_level *= factor
        self.ref_pixels = [[p[0] * factor, p[1] * factor] for p in self.ref_pixels]
        if len(self.ref_pixels) == 3: self.calculate_mapping()
        self.render_map()

    def calculate_mapping(self):
        src = np.column_stack([self.ref_coords, np.ones(3)])
        dst = np.array(self.ref_pixels)
        self.M, _, _, _ = np.linalg.lstsq(src, dst, rcond=None)

    def on_map_click(self, event):
        if len(self.ref_pixels) >= 3:
            return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        coord_str = simpledialog.askstring("Input", "Lat Lon (e.g. 45.1 7.2):")
        if coord_str:
            try:
                lat, lon = map(float, coord_str.replace(",", " ").split())
                self.ref_pixels.append([x, y])
                self.ref_coords.append([lat, lon])
                self.canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="red")
                if len(self.ref_pixels) == 3:
                    self.calculate_mapping()
                    messagebox.showinfo("Save calibration","Save calibration as a txt file *.txt")
                    self.save_calibration()
            except:
                pass

    def load_gpx(self):
        if self.M is None:
            messagebox.showwarning("Warning", "Please load calibration or calibrate map first.")
            return
        path = filedialog.askopenfilename(filetypes=[("GPX", "*.gpx")])
        if path:
            with open(path, 'r', encoding="utf-8") as f:
                gpx = gpxpy.parse(f)
                self.track_pts = []
                self.track_distances = [0.0]

                temp_pts = []
                for track in gpx.tracks:
                    for seg in track.segments:
                        for p in seg.points:
                            temp_pts.append({'lat': p.latitude, 'lon': p.longitude, 'time': p.time})

                self.track_pts = temp_pts

                total_dist = 0.0
                for i in range(1, len(self.track_pts)):
                    p1 = (self.track_pts[i - 1]['lat'], self.track_pts[i - 1]['lon'])
                    p2 = (self.track_pts[i]['lat'], self.track_pts[i]['lon'])
                    total_dist += geodesic(p1, p2).km
                    self.track_distances.append(total_dist)

                if self.track_pts:
                    self.start_time = self.track_pts[0]['time']
                    self.last_split_time = self.start_time
                    self.slider.config(to=len(self.track_pts) - 1)
                    self.slider.set(0)

    def update_plot(self, val):
        if not self.track_pts or self.M is None: return
        idx = int(val)
        elapsed = (self.track_pts[idx]['time'] - self.start_time).total_seconds()
        self.time_label.config(text=self.format_seconds(elapsed))
        current_dist = self.track_distances[idx]
        self.dist_label.config(text=f"{current_dist:.2f} km")

        self.canvas.delete("runner")
        start = max(0, idx - 40)
        pts = []
        for i in range(start, idx + 1):
            p = self.track_pts[i]
            px = np.dot([p['lat'], p['lon'], 1], self.M)
            pts.append((px[0], px[1]))
        if len(pts) > 1: self.canvas.create_line(pts, fill="blue", width=3, tags="runner")
        hx, hy = pts[-1]
        self.canvas.create_oval(hx - 6, hy - 6, hx + 6, hy + 6, fill="orange", outline="black", tags="runner")

    def toggle_play(self):
        self.is_playing = not self.is_playing
        self.play_btn.config(text="Pause" if self.is_playing else "Play")
        if self.is_playing: self.play_loop()

    def play_loop(self):
        if self.is_playing:
            curr = self.slider.get()
            if curr < len(self.track_pts) - 1:
                self.slider.set(curr + 1)
                self.root.after(self.speed_var.get(), self.play_loop)
            else:
                self.is_playing = False
                self.play_btn.config(text="Play")


if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("1400x850")
    app = OrienteeringAnalyser(root)
    root.mainloop()