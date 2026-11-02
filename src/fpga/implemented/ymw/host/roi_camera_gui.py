"""Windows entry point for the responsive ROI acquisition GUI."""
import argparse
import tkinter as tk
from roi_gui_live import LiveApp as App
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--bind',default='192.168.0.3');parser.add_argument('--board',default='192.168.0.2');parser.add_argument('--port',type=int,default=5000)
    parser.add_argument('--self-test',action='store_true',help='Construct and close the GUI without any board commands')
    args=parser.parse_args();root=tk.Tk()
    if args.self_test:root.withdraw()
    app=App(root,args)
    if args.self_test:
        root.update_idletasks();assert len(app.cards)==4 and len(app.inputs)==5
        root.destroy();print('ROI_GUI_SELF_TEST_PASS; no board commands sent');return
    root.mainloop()
if __name__=='__main__':main()
