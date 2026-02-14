# GUI Mission Control

# This is the main GUI for the mission control system.
# All components are initialized here.

import tkinter as tk
from tkinter import messagebox

class MissionControl:
    def __init__(self, master):
        self.master = master
        self.master.title("Mission Control")

        # Create widgets
        self.start_button = tk.Button(master, text='Start Mission', command=self.start_mission)
        self.start_button.pack()

        self.stop_button = tk.Button(master, text='Stop Mission', command=self.stop_mission)
        self.stop_button.pack()

    def start_mission(self):
        messagebox.showinfo('Info', 'Mission Started!')

    def stop_mission(self):
        messagebox.showinfo('Info', 'Mission Stopped!')

if __name__ == '__main__':
    root = tk.Tk()
    mission_control = MissionControl(root)
    root.mainloop()