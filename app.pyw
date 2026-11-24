"""Windows 데스크톱 파일 묶음 검토 앱."""
if __name__ == "__main__":
    from pathlib import Path
    import os
    import sys
    if "--legacy" not in sys.argv:
        os.startfile(Path(__file__).resolve().with_name("start.cmd"))
        raise SystemExit

import sqlite3
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from itertools import groupby
from tkinter import ttk, filedialog, messagebox, simpledialog
sys.dont_write_bytecode=True
import engine
import storage
import feedback
from course_source import group_scope
from readers import course_cover
from similarity import compare

from tkinter import font as tkfont
from ui_theme import (BG, WHITE, INK, TEXT, MUTED, LINE, TEAL, PALE, NAVY,
                      RAIL_TEXT, RAIL_LINE, RAIL_ACTIVE, AMBER, GREEN, font,
                      label, button, card, scrollbar, fit_text, create_window, setup_theme)


class App:
    def px(self, logical_pixels):
        return round(logical_pixels*self.scale)

    def __init__(self, w):
        self.w = w
        self.scale = round(w.winfo_fpixels("1i"))/96
        w.title("다운로드 정리")
        w.configure(bg=BG)
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        width, height = min(self.px(1280), sw-self.px(36)), min(self.px(850), sh-self.px(68))
        w.geometry(f"{width}x{height}+{max(2,(sw-width)//2)}+{max(2,(sh-height)//2-12)}")
        w.minsize(min(self.px(880),width), min(self.px(580),height))
        self.current = self.path = self.last_pair = None
        self.busy = self.closed = False
        self.view, self.scope, self.kind = "files", "all", ""
        self.checked = set()
        _,deep,course_covers = storage.scan_options()
        self.deep = tk.BooleanVar(value=deep)
        self.course_covers = tk.BooleanVar(value=course_covers)
        self.rowpg, self.colpg = tk.StringVar(value="1"), tk.StringVar(value="1")
        self.matrix_scope = tk.StringVar()
        self.queue, self.stop = queue.Queue(), threading.Event()
        self.icons = setup_theme(w,self.scale)
        w.iconphoto(True,self.icons["brand"])
        self.small_face = tkfont.Font(w, font=font(9))
        self.detail_mode = "reason"
        self.tab_buttons, self.panels, self.options = {}, {}, []

        w.grid_columnconfigure(1, weight=1)
        w.grid_rowconfigure(0, weight=1)
        self.setup_sidebar()
        workspace = tk.Frame(w, bg=BG, padx=self.px(20), pady=self.px(16))
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(2, weight=1)
        self.setup_header(workspace)
        self.setup_metrics(workspace)
        for key in self.tab_buttons:
            self.panels[key] = card(workspace)
            self.panels[key].grid(row=2, column=0, sticky="nsew")
        self.setup_files()
        self.setup_matrix()
        self.setup_flow()
        self.setup_footer(workspace)
        self.tab("files")
        self.buttons()
        w.protocol("WM_DELETE_WINDOW", self.close)
        self.timer = w.after(100, self.poll)
        self.start_timer = w.after(120, self.analyze)

    def setup_sidebar(self):
        rail = tk.Frame(self.w, bg=NAVY, width=self.px(209))
        rail.grid(row=0,column=0,sticky="nsew")
        rail.grid_propagate(False)
        rail.columnconfigure(0,weight=1)
        rail.rowconfigure(3,weight=1)
        navigation=tk.Frame(rail,bg=NAVY)
        navigation.grid(row=0,column=0,sticky="ew",padx=11,pady=(self.px(16),0))
        for key,title in (("files","파일 검토"),("matrix","유사도 행렬"),("flow","분석 과정")):
            item = tk.Button(navigation,text="   "+title,command=lambda k=key:self.tab(k),
                             anchor="w",compound="left",image=self.icons[f"nav_{key}_idle"],
                             font=font(11,True),relief="flat",bd=0,padx=13,pady=7,
                             bg=NAVY,fg=RAIL_TEXT,activebackground=RAIL_ACTIVE,
                             activeforeground=WHITE,highlightthickness=0,cursor="hand2")
            item.pack(fill="x",pady=2)
            self.tab_buttons[key]=item

        tk.Frame(rail,bg=RAIL_LINE,height=1).grid(row=1,column=0,sticky="ew",padx=18,pady=(14,10))
        label(rail,"추천 그룹",9,True,"#BDB5CE",NAVY).grid(row=2,column=0,sticky="w",padx=22,pady=(0,5))
        nav_area = tk.Frame(rail,bg=NAVY)
        nav_area.grid(row=3,column=0,sticky="nsew",padx=11)
        nav_area.columnconfigure(0,weight=1)
        nav_area.rowconfigure(0,weight=1)
        self.nav=ttk.Treeview(nav_area,columns=("title","count"),show="",selectmode="browse",
                              style="Rail.Treeview",height=2)
        self.nav.column("title",width=self.px(118),minwidth=self.px(50),stretch=True)
        self.nav.column("count",width=self.px(39),minwidth=self.px(25),stretch=False,anchor="center")
        self.nav.grid(row=0,column=0,sticky="nsew")
        scrollbar(nav_area,self.nav,"vertical",0,1)
        self.nav.bind("<<TreeviewSelect>>",self.nav_changed)
        self.nav.bind("<ButtonRelease-1>",self.nav_reopen)
        self.nav.bind("<Return>",self.nav_reopen)

        tools=tk.Frame(rail,bg=NAVY)
        tools.grid(row=4,column=0,sticky="sew",padx=17,pady=(8,12))
        tk.Frame(tools,bg=RAIL_LINE,height=1).pack(fill="x",pady=(0,11))
        label(tools,"분석 설정",9,True,"#BDB5CE",NAVY).pack(anchor="w",padx=4,pady=(0,4))
        for title,var in (("애매한 파일만 본문 분석",self.deep),
                          ("강의 표지로 과목명 찾기",self.course_covers)):
            check = tk.Checkbutton(tools,text=title,variable=var,command=self.changed,
                                   font=font(10),bg=NAVY,fg=WHITE,activebackground=NAVY,
                                   activeforeground=WHITE,selectcolor=RAIL_ACTIVE,anchor="w",
                                   highlightthickness=0,bd=0,cursor="hand2")
            check.pack(fill="x",pady=2)
            self.options.append(check)
        runbar=tk.Frame(tools,bg=NAVY)
        runbar.pack(fill="x",pady=(8,0))
        self.rescan=button(runbar,"다시 분석",self.analyze,dark=True)
        self.rescan.pack(side="left",fill="x",expand=True)
        self.connect_lms=button(tools,"브라우저 출처 연결",self.setup_lms,dark=True)
        self.connect_lms.pack(fill="x",pady=(5,0))
        self.cancel=button(runbar,"취소",self.stop.set,dark=True)
        self.status=label(rail,"준비 중",9,False,RAIL_TEXT,NAVY,wraplength=self.px(172))
        self.status.grid(row=5,column=0,sticky="w",padx=21,pady=(0,16))

    def setup_lms(self):
        from browser_bridge import register
        try:
            path=register()
        except OSError as error:
            messagebox.showerror("브라우저 출처 연결",str(error),parent=self.w)
            return
        self.w.clipboard_clear()
        self.w.clipboard_append(str(path))
        messagebox.showinfo("브라우저 출처 연결",
            "확장 폴더 경로를 복사했습니다.\n\n"
            "1. Edge에서 edge://extensions 를 엽니다. Chrome은 chrome://extensions 입니다.\n"
            "2. 개발자 모드를 켜고 ‘압축 풀린 파일 로드’를 선택합니다.\n"
            "3. 복사한 폴더 경로를 붙여넣고 선택합니다.\n"
            "4. 출처를 기록할 HTTPS 웹페이지에서 확장 아이콘 → ‘이 사이트 연결’을 누른 뒤 새로고침하세요. 조선대 e-Class는 기본 연결됩니다.\n\n"
            "다운로드 후 ‘다시 분석 → 파일 정보 보기’에서 페이지 제목, 출처 주소와 확인 가능한 강좌명을 볼 수 있습니다.",
            parent=self.w)

    def setup_header(self, parent):
        head=tk.Frame(parent,bg=BG)
        head.grid(row=0,column=0,sticky="ew",pady=(0,16))
        head.columnconfigure(0,weight=1)
        self.page_title=label(head,"파일 검토",23,True,INK,BG)
        self.page_title.grid(row=0,column=0,sticky="w")
        self.organize_btn=button(head,"그룹별 폴더로 정리",self.organize_groups,True)
        self.organize_btn.grid(row=0,column=1,rowspan=2,sticky="e",padx=(self.px(12),0))
        location=tk.Frame(head,bg=BG)
        location.grid(row=1,column=0,sticky="ew",pady=(4,0))
        location.columnconfigure(1,weight=1)
        self.path_kind=label(location,"내 다운로드",9,True,TEAL,PALE)
        self.path_kind.grid(row=0,column=0,sticky="w",ipadx=6,ipady=1,padx=(0,7))
        self.pathlabel=label(location,"폴더 준비 중",9,False,MUTED,BG,width=1)
        self.pathlabel.grid(row=0,column=1,sticky="ew")
        self.pathlabel.bind("<Configure>",lambda event:self.update_path())

    def update_path(self):
        if self.path:
            self.pathlabel.configure(text=fit_text(str(self.path),self.pathlabel.winfo_width(),
                                                   self.small_face,middle=True))

    def setup_metrics(self, parent):
        self.metrics=tk.Frame(parent,bg=BG)
        self.metrics.grid(row=1,column=0,sticky="ew",pady=(0,14))
        self.metrics.columnconfigure((0,1,2),weight=1,uniform="cards")
        self.metric_values=[]
        for col,(title,icon,bg) in enumerate((("전체 파일","files","#F1EDFC"),
                                               ("추천 그룹","folder","#EFF7F4"),
                                               ("미분류 파일","inbox","#FCF5ED"))):
            tile=card(self.metrics,bg)
            tile.grid(row=0,column=col,sticky="ew",padx=(0,8 if col<2 else 0))
            tk.Label(tile,image=self.icons["metric_"+icon],bg=bg,bd=0).grid(
                row=0,column=0,rowspan=2,padx=(14,11),pady=11)
            label(tile,title,9,True,MUTED,bg).grid(row=0,column=1,sticky="sw",pady=(7,0))
            number=label(tile,"—",22,True,INK,bg)
            number.grid(row=1,column=1,sticky="nw",pady=(0,7))
            self.metric_values.append(number)

    def setup_files(self):
        p=self.panels["files"]
        p.columnconfigure(0,weight=1)
        p.rowconfigure(1,weight=1)
        title=tk.Frame(p,bg=WHITE)
        title.grid(row=0,column=0,sticky="ew",padx=16,pady=(11,9))
        title.columnconfigure(0,weight=1)
        self.group_title=label(title,"전체 파일",15,True,INK,width=1)
        self.group_title.grid(row=0,column=0,sticky="ew")
        self.group_meta=label(title,"",9,True,MUTED)
        self.group_meta.grid(row=0,column=1,sticky="e",padx=(6,0))
        self.course_btn=button(title,"파일명 변경",self.review_course_title)
        self.course_btn.grid(row=0,column=2,sticky="e",padx=(self.px(9),0))
        self.title_note=label(title,"",9,False,MUTED)
        self.title_note.grid(row=1,column=0,columnspan=3,sticky="w",pady=(4,0))
        self.course_btn.grid_remove()
        self.title_note.grid_remove()
        area=tk.Frame(p,bg=WHITE)
        area.grid(row=1,column=0,sticky="nsew",padx=1)
        area.columnconfigure(0,weight=1)
        area.rowconfigure(0,weight=1)
        self.tree=ttk.Treeview(area,columns=("name","group","state","confidence","source"),
                               show="tree headings",selectmode="browse",height=3)
        self.tree.column("#0",width=self.px(60),minwidth=self.px(60),stretch=False)
        self.tree.heading("#0",text="선택",anchor="w")
        for key,title,width,minimum,stretch,anchor in (
                ("name","파일명",245,150,True,"w"),("group","그룹",110,70,False,"w"),("state","판정",90,72,False,"w"),
                ("confidence","신뢰도",80,60,False,"center"),("source","다운로드 출처",128,90,True,"w")):
            self.tree.heading(key,text=title,anchor=anchor)
            self.tree.column(key,width=self.px(width),minwidth=self.px(minimum),stretch=stretch,anchor=anchor)
        self.tree.tag_configure("odd",background="#FAF9FC")
        self.tree.tag_configure("hold",foreground=AMBER)
        self.tree.tag_configure("extra",foreground=GREEN)
        self.tree.grid(row=0,column=0,sticky="nsew")
        scrollbar(area,self.tree,"vertical",0,1)
        scrollbar(area,self.tree,"horizontal",1,0)
        self.tree.bind("<Button-1>",self.tree_click)
        self.tree.bind("<space>",self.key_check)
        self.tree.bind("<<TreeviewSelect>>",lambda e:self.file_detail())
        self.tree.bind("<Configure>",lambda event:self.fit_file_columns())
        self.empty_label=label(area,"표시할 파일이 없습니다.",11,False,MUTED)
        tk.Frame(p,bg=LINE,height=1).grid(row=2,column=0,sticky="ew")
        detail=tk.Frame(p,bg=WHITE)
        detail.grid(row=3,column=0,sticky="ew",padx=15,pady=(8,10))
        detail.columnconfigure(0,weight=1)
        self.detail_heading=label(detail,"판정 근거",11,True,INK,width=1)
        self.detail_heading.grid(row=0,column=0,sticky="ew")
        self.detail_switch=button(detail,"파일 정보 보기",self.toggle_detail)
        self.detail_switch.configure(font=font(9,True),pady=3,padx=9)
        self.detail_switch.grid(row=0,column=1,sticky="e",padx=(6,0))
        box=tk.Frame(detail,bg=WHITE)
        box.grid(row=1,column=0,columnspan=2,sticky="ew",pady=(5,0))
        box.columnconfigure(0,weight=1)
        self.details=tk.Text(box,height=3,width=1,bg=WHITE,fg=TEXT,font=font(10),
                             bd=0,highlightthickness=0,wrap="word",spacing3=3,state="disabled")
        self.details.grid(row=0,column=0,sticky="ew")
        self.details.tag_configure("note",font=font(11,True),foreground=TEXT)
        self.details.tag_configure("meta",foreground=MUTED)
        scrollbar(box,self.details,"vertical",0,1)

    def setup_footer(self, parent):
        self.footer=tk.Frame(parent,bg=BG)
        self.footer.grid(row=3,column=0,sticky="ew",pady=(10,0))
        self.footer.columnconfigure(1,weight=1)
        self.all_btn=button(self.footer,"표시 항목 선택",self.toggle_all)
        self.all_btn.grid(row=0,column=0,sticky="w")
        self.selection=label(self.footer,"",9,True,MUTED,BG)
        self.selection.grid(row=0,column=1,sticky="w",padx=7)
        self.undo_btn=button(self.footer,"최근 이동 되돌리기",self.undo)
        self.undo_btn.grid(row=0,column=2,padx=(3,0))
        self.assign_btn=button(self.footer,"그룹 편집 ▾",self.edit_menu)
        self.assign_btn.grid(row=0,column=3,padx=(6,0))
        self.move_btn=button(self.footer,"체크한 파일 이동",self.move,True)
        self.move_btn.grid(row=0,column=4,padx=(6,0))

    def setup_matrix(self):
        p=self.panels["matrix"]
        p.columnconfigure(0,weight=1)
        p.rowconfigure(1,weight=1)
        head=tk.Frame(p,bg=WHITE)
        head.grid(row=0,column=0,sticky="ew",padx=16,pady=(12,4))
        self.pagers=[]
        for name,var in (("행",self.rowpg),("열",self.colpg)):
            label(head,name+" 페이지",9,True,MUTED).pack(side="left",padx=(0,4))
            cb=ttk.Combobox(head,width=3,state="readonly",textvariable=var,values=["1"])
            cb.pack(side="left",padx=(0,10))
            self.pagers.append(cb)
            cb.bind("<<ComboboxSelected>>",lambda e:self.draw_matrix(True))
        label(head,"",9,False,MUTED,textvariable=self.matrix_scope).pack(side="right")
        area=tk.Frame(p,bg=WHITE)
        area.grid(row=1,column=0,sticky="nsew",padx=12,pady=(4,8))
        area.columnconfigure(0,weight=1)
        area.rowconfigure(0,weight=1)
        self.heat=tk.Canvas(area,bg=WHITE,highlightthickness=0,width=1,height=1)
        self.heat.grid(row=0,column=0,sticky="nsew")
        scrollbar(area,self.heat,"vertical",0,1)
        scrollbar(area,self.heat,"horizontal",1,0)
        self.heat.bind("<Configure>",lambda e:self.draw_matrix())
        self.heat.bind("<Button-1>",self.cell_click)
        self.heat.bind("<MouseWheel>",lambda e:self.heat.yview_scroll(-int(e.delta/120),"units"))
        tk.Frame(p,bg=LINE,height=1).grid(row=2,column=0,sticky="ew")
        label(p,"선택한 두 파일의 근거",11,True,INK).grid(row=3,column=0,sticky="w",padx=16,pady=(10,4))
        box=tk.Frame(p,bg=WHITE)
        box.grid(row=4,column=0,sticky="ew",padx=16)
        box.columnconfigure(0,weight=1)
        self.pair=tk.Text(box,height=4,width=1,bg=WHITE,fg=TEXT,font=font(10),wrap="word",
                          relief="flat",highlightthickness=0,spacing3=2,state="disabled")
        self.pair.grid(row=0,column=0,sticky="ew")
        scrollbar(box,self.pair,"vertical",0,1)
        actions=tk.Frame(p,bg=WHITE)
        actions.grid(row=5,column=0,sticky="w",padx=16,pady=(4,12))
        self.relation_buttons=[]
        for kind,title in (("must","같은 그룹"),("cannot","다른 그룹"),("clear","관계 해제")):
            b=button(actions,title,lambda k=kind:self.relation(k))
            b.pack(side="left",padx=(0,6))
            self.relation_buttons.append(b)

    def setup_flow(self):
        p=self.panels["flow"]
        p.columnconfigure(0,weight=1)
        p.rowconfigure(1,weight=1)
        self.flow_summary=label(p,"이번 분석",14,True,INK)
        self.flow_summary.grid(row=0,column=0,sticky="w",padx=18,pady=(14,9))
        self.flow=tk.Text(p,wrap="word",relief="flat",font=font(10),bg=WHITE,fg=TEXT,
                          padx=18,pady=2,spacing3=4,state="disabled",width=1,height=1)
        self.flow.tag_configure("h",font=font(12,True),foreground=TEAL,spacing1=6,spacing3=4)
        self.flow.grid(row=1,column=0,sticky="nsew",pady=(0,10))
        scrollbar(p,self.flow,"vertical",1,1)


    @staticmethod
    def put(widget,text):
        widget.configure(state="normal");widget.delete("1.0","end");widget.insert("1.0",text);widget.configure(state="disabled")
    def changed(self):self.status.config(text="설정 변경됨 · 다시 분석을 누르세요")
    def close(self):
        if self.busy and self.kind in ("move","organize","undo"):
            self.status.config(text="파일 처리가 끝나면 창을 닫을 수 있습니다.");return
        self.closed=True;self.stop.set()
        self.w.after_cancel(self.timer);self.w.after_cancel(self.start_timer);self.w.destroy()
    def buttons(self):
        for control in [self.rescan,*self.options]:
            control.configure(state="disabled" if self.busy else "normal")
        if self.busy and self.kind=="scan":self.cancel.pack(side="left",padx=5)
        else:self.cancel.pack_forget()
        self.undo_btn.configure(state="disabled" if self.busy else "normal")
        self.update_checks()
    def work(self,kind,task):
        if self.busy:return
        self.kind=kind;self.busy=True;self.stop.clear();self.buttons()
        def run():
            try:self.queue.put(("result",kind,task()))
            except InterruptedError:self.queue.put(("cancel",kind,None))
            except Exception as e:self.queue.put(("error",kind,str(e)))
        threading.Thread(target=run,daemon=True).start()
    def poll(self):
        if self.closed:return
        while True:
            try:action,kind,value=self.queue.get_nowait()
            except queue.Empty:break
            if action=="status":self.status.configure(text=value);continue
            self.busy=False;self.kind=""
            if action=="error":
                if kind=="scan":self.clear_result()
                self.status.configure(text="처리 중단");messagebox.showerror("처리 오류",value,parent=self.w)
            elif action=="cancel":self.status.configure(text="분석 취소됨")
            elif kind=="scan":self.bind_result(value)
            elif kind=="course_title":self.confirm_course_title(*value)
            else:
                folder=self.current.root if kind=="organize" else None
                title="그룹별 폴더 정리 결과" if folder else "파일 처리 결과"
                self.popup(title,str(folder) if folder else "파일별 결과", "\n".join(value) or "처리할 파일이 없습니다.",open_folder=folder)
                self.analyze()
            self.buttons()
        self.timer=self.w.after(80,self.poll)
    def analyze(self):
        if self.busy:return
        sub,deep,course_covers=False,self.deep.get(),self.course_covers.get()
        try:
            path=storage.downloads_folder()
        except OSError as error:
            self.clear_result()
            self.path=None
            self.pathlabel.configure(text="다운로드 폴더 위치를 확인할 수 없습니다.")
            self.status.configure(text="다운로드 위치 확인 필요")
            messagebox.showerror("다운로드 폴더",str(error),parent=self.w)
            return
        if self.current and self.current.root!=path:self.clear_result()
        self.path=path
        self.update_path()
        def check():
            if self.stop.is_set():raise InterruptedError()
        def task():
            return engine.analyze(path,sub,deep,check,lambda msg:self.queue.put(("status","scan",msg)),
                                  course_covers=course_covers)
        self.status.configure(text="다운로드 분석 준비 중");self.work("scan",task)
    def clear_result(self):
        self.current=self.last_pair=self.hit=None
        self.scope="all"
        self.checked.clear()
        self.nav.delete(*self.nav.get_children())
        self.fill_files()
        for tile in self.metric_values:tile.configure(text="—")
        self.heat.delete("all")
        self.put(self.pair,"")
        for control in self.relation_buttons:control.configure(state="disabled")
        self.put(self.flow,"")
        self.flow_summary.configure(text="이번 분석")
        self.matrix_scope.set("")
    def bind_result(self,result):
        self.current=result;self.path=result.root;self.checked.clear();self.last_pair=None
        storage.remember_options(False,result.deep,self.course_covers.get())
        self.update_path()
        pages=[str(x) for x in range(1,max(1,(len(result.files)+11)//12)+1)]
        for box in self.pagers:box.configure(values=pages)
        self.rowpg.set("1");self.colpg.set("1")
        self.matrix_scope.set("진한 보라색일수록 유사도가 높습니다")
        self.heat.xview_moveto(0)
        self.heat.yview_moveto(0)
        self.fill_nav("all");self.fill_flow();self.tab("files");self.stats()
    def stats(self):
        s=self.current
        held=sum(f.group is None for f in s.files)
        for tile,count in zip(self.metric_values,(len(s.files),len(s.groups),held)):
            tile.configure(text=f"{count:,}")
        self.status.configure(text="분석 완료")
    def fill_nav(self,which):
        s=self.current
        self.scopes=["all",*s.groups,"hold"]
        self.nav.delete(*self.nav.get_children())
        rows=[("전체 파일",len(s.files)),*((g.title,len(g.members)) for g in s.groups),
              ("미분류",sum(f.group is None for f in s.files))]
        for index,(title,count) in enumerate(rows):
            self.nav.insert("","end",iid=str(index),values=("   "+title,f"{count:,}"))
        pos=self.scopes.index(which) if which in self.scopes else 0
        self.scope=self.scopes[pos]
        self.nav.selection_set(str(pos))
        self.nav.focus(str(pos))
        self.nav.see(str(pos))
        self.fill_files()
    def nav_changed(self,event=None):
        selection=self.nav.selection()
        if not selection or not self.current:return
        scope=self.scopes[int(selection[0])]
        if self.scope != scope:
            self.scope=scope
            self.tab("files")
            self.fill_files()
    def nav_reopen(self,event):
        if self.nav.selection() and (event.keysym=="Return" or self.nav.identify_row(event.y)):
            self.tab("files")
    def visible(self):
        if not self.current:return []
        if self.scope=="all":return self.current.files
        if self.scope=="hold":return [f for f in self.current.files if not f.group]
        return sorted(self.scope.members,key=lambda f:f.index)
    def fit_file_columns(self):
        width=self.tree.winfo_width()
        if width<2:return
        group_width=max(self.px(90),min(self.px(140),width//8)) if self.scope=="all" else 0
        source_width=max(self.px(110),min(self.px(240),width//4))
        fixed_width=sum(self.tree.column(key,"width") for key in ("#0","state","confidence"))
        name_width=max(self.px(150),width-fixed_width-source_width-group_width)
        for key,size in (("group",group_width),("source",source_width),("name",name_width)):
            if size:self.tree.column(key,width=size,stretch=False)
    def fill_files(self):
        self.tree.delete(*self.tree.get_children());arr=self.visible()
        title="전체 파일" if self.scope=="all" else "미분류" if self.scope=="hold" else self.scope.title
        group_conf=""
        if getattr(self.scope,"confidence",None) is not None:
            group_conf=f"    ·    추천 신뢰도 {self.scope.confidence:.2f}"
        self.group_title.config(text=title)
        self.group_meta.config(text=f"파일 {len(arr):,}개"+group_conf)
        if hasattr(self.scope,"title_note"):
            self.title_note.configure(text=self.scope.title_note)
            self.title_note.grid()
            self.course_btn.grid()
        else:
            self.title_note.grid_remove()
            self.course_btn.grid_remove()
        columns=("name","group","state","confidence","source") if self.scope=="all" else ("name","state","confidence","source")
        self.tree.configure(displaycolumns=columns)
        self.fit_file_columns()
        for i,f in enumerate(arr):
            state="hold" if f.group is None else "extra" if f.state=="2차 추천" else "base"
            self.tree.insert("","end",iid=str(f.index),values=self.values(f),image=self.row_image(f),
                             tags=(state,"odd" if i%2 else "even"))
        if arr:
            self.empty_label.place_forget()
        else:
            self.empty_label.configure(text="미분류 파일이 없습니다." if self.scope=="hold" else "표시할 파일이 없습니다.")
            self.empty_label.place(relx=.5,rely=.56,anchor="center")
        if arr:self.tree.selection_set(str(arr[0].index));self.tree.focus(str(arr[0].index))
        self.file_detail();self.update_checks()
    def values(self,f):
        score="—" if f.confidence is None else f"{f.confidence:.2f}"
        return (f.name,f.group.title if f.group else "미분류",f.state,score,f.host or "—")
    def row_image(self,f):
        kind={"pdf":"pdf","ppt":"slides","pptx":"slides","zip":"archive","7z":"archive",
              "docx":"doc","doc":"doc","hwp":"doc","hwpx":"doc","xlsx":"sheet","csv":"sheet"}.get(f.ext,"other")
        return self.icons[f"row_{kind}_{int(f.index in self.checked)}"]
    def tree_click(self,e):
        iid=self.tree.identify_row(e.y)
        if iid and self.tree.identify_column(e.x)=="#0" and not self.busy:
            self.tree.focus_set()
            self.tree.selection_set(iid);self.tree.focus(iid);self.flip(int(iid));return "break"
    def key_check(self,e):
        if self.tree.selection() and not self.busy:self.flip(int(self.tree.selection()[0]))
        return "break"
    def flip(self,i):
        self.checked.symmetric_difference_update({i});f=self.current.files[i];self.tree.item(str(i),image=self.row_image(f));self.update_checks()
    def toggle_all(self):
        arr=self.visible();turn=any(f.index not in self.checked for f in arr)
        for f in arr:
            if turn:self.checked.add(f.index)
            else:self.checked.discard(f.index)
            self.tree.item(str(f.index),image=self.row_image(f))
        self.update_checks()
    def update_checks(self):
        if not hasattr(self,"move_btn"):return
        arr=self.visible();n=sum(f.index in self.checked for f in arr)
        review=self.view=="files" and not self.busy
        self.course_btn.configure(state="normal" if review and hasattr(self.scope,"members") else "disabled")
        can_organize=review and self.current and self.current.groups and self.scope!="hold"
        self.organize_btn.configure(text="이 그룹을 폴더로 정리" if hasattr(self.scope,"members") else "그룹별 폴더로 정리",
                                    state="normal" if can_organize else "disabled",
                                    bg=TEAL if can_organize else "#E2DEEA")
        self.selection.config(text=f"{n}개 선택")
        self.move_btn.config(state="normal" if review and n else "disabled",
                             bg=TEAL if review and n else "#E2DEEA")
        self.assign_btn.config(state="normal" if review and arr else "disabled");self.all_btn.config(state="normal" if review and arr else "disabled",text="전체 선택 해제" if arr and n==len(arr) else "표시 항목 선택")
    def toggle_detail(self):
        self.detail_mode="info" if self.detail_mode=="reason" else "reason"
        self.file_detail()

    def file_detail(self):
        selection=self.tree.selection()
        info=self.detail_mode=="info"
        heading="파일 정보" if info else "판정 근거"
        self.detail_switch.configure(text="판정 근거 보기" if info else "파일 정보 보기",
                                     state="normal" if selection else "disabled")
        self.details.configure(height=6 if info else 4)
        if not selection or not self.current:
            self.detail_heading.configure(text=heading)
            self.put(self.details,"파일을 선택하면 자세한 내용을 볼 수 있습니다.")
            return
        f=self.current.files[int(selection[0])]
        self.detail_heading.configure(text=f"{heading}   ·   {f.name}")
        if info:
            created=datetime.fromtimestamp(f.created).strftime("%Y-%m-%d %H:%M")
            modified=datetime.fromtimestamp(f.modified).strftime("%Y-%m-%d %H:%M")
            lines=[f"정규화한 이름   {f.normalized or '단서 없음'}",
                   f"순번 {f.sequence or '없음'}    ·    역할 {', '.join(f.roles) or '없음'}    ·    버전 {', '.join(f.versions) or '없음'}",
                   f"{f.ext.upper() or '확장자 없음'}    ·    {f.size:,} B    ·    다운로드 출처 {f.host or '기록 없음'}",
                   f"생성 {created}    ·    수정 {modified}",str(f.path)]
            if f.download.page_title or f.download.course_name or f.download.source_page:
                lines.insert(0,f"다운로드 당시 강좌명   {f.download.course_name or '확인되지 않음'}\n페이지 제목   {f.download.page_title or '기록 없음'}\n출처 페이지   {f.download.source_page or '기록 없음'}")
        else:
            lines=[f.note,f.evidence,f"1차 신뢰도 {f.first_band}    ·    분류용 본문 {f.excerpt_status or '읽지 않음'}"]
            if f.course_cover_checked:lines[-1]+="    ·    과목명용 표지 확인 시도"
        self.put(self.details,"\n".join(lines))
        if not info:
            self.details.tag_add("note","1.0","1.end")
            self.details.tag_add("meta","3.0","end-1c")
        self.details.yview_moveto(0)
    def tab(self,key):
        self.view=key;self.panels[key].tkraise()
        self.page_title.configure(text={"files":"파일 검토","matrix":"유사도 행렬","flow":"분석 과정"}[key])
        self.nav.configure(style="Rail.Treeview" if key=="files" else "Quiet.Rail.Treeview")
        for k,b in self.tab_buttons.items():
            active=k==key
            b.configure(bg=RAIL_ACTIVE if active else NAVY,fg=WHITE if active else RAIL_TEXT,
                        image=self.icons[f"nav_{k}_{'active' if active else 'idle'}"])
        for section in (self.metrics,self.footer,self.organize_btn):
            if key=="files":section.grid()
            else:section.grid_remove()
        if key=="matrix":self.w.after_idle(self.draw_matrix)
        self.update_checks()
    def draw_matrix(self,reset=False):
        if not self.current or self.view!="matrix":return
        if reset:
            self.last_pair=None
            self.heat.xview_moveto(0)
            self.heat.yview_moveto(0)
        cv=self.heat;cv.delete("all");n=len(self.current.files)
        if not n:
            self.hit=None
            cv.configure(scrollregion=(0,0,0,0))
            cv.create_text(max(90,cv.winfo_width()//2),max(30,cv.winfo_height()//2),
                           text="비교할 파일이 없습니다.",font=font(11),fill=MUTED)
            self.put(self.pair,"비교할 파일이 없습니다.")
            for b in self.relation_buttons:b.configure(state="disabled")
            return
        ww,hh=cv.winfo_width(),cv.winfo_height()
        if ww<80 or hh<60:return
        r0=(int(self.rowpg.get())-1)*12;c0=(int(self.colpg.get())-1)*12
        nr=min(n-r0,12);nc=min(n-c0,12)
        left=min(self.px(230),max(self.px(158),ww//4));top=self.px(31)
        cw=max(self.px(43),min(self.px(75),(ww-left-4)/max(1,nc)))
        rh=max(self.px(26),min(self.px(38),(hh-top-4)/max(1,nr)))
        cv.configure(scrollregion=(0,0,left+nc*cw+3,top+nr*rh+3))
        self.hit=(r0,c0,nr,nc,left,top,cw,rh)
        if not self.last_pair or not (r0<=self.last_pair[0]<r0+nr and c0<=self.last_pair[1]<c0+nc):
            self.last_pair=(r0,c0+(1 if nc>1 else 0))
        for j in range(nc):cv.create_text(left+(j+.5)*cw,top/2,text=f"#{c0+j+1}",font=font(9,True),fill=MUTED)
        for i in range(nr):
            y=top+i*rh;f=self.current.files[r0+i]
            name=fit_text(f.name,left-self.px(44),self.small_face,middle=True)
            cv.create_text(3,y+rh/2,anchor="w",text=f"#{r0+i+1}",font=font(9,True),fill=MUTED)
            cv.create_text(self.px(36),y+rh/2,anchor="w",text=name,font=font(9),fill=TEXT)
            for j in range(nc):
                a,b=r0+i,c0+j;v=self.current.matrix[a][b];x=left+j*cw
                fill="#E7E5EC" if a==b else "#%02x%02x%02x"%(round(247-157*v/100),round(245-191*v/100),round(252-96*v/100))
                selected=(a,b)==self.last_pair
                cv.create_rectangle(x+1,y+1,x+cw-1,y+rh-1,fill=fill,outline=INK if selected else "",width=3 if selected else 0)
                cv.create_text(x+cw/2,y+rh/2,text=f"{v/100:.2f}",font=font(9,selected),fill=WHITE if v>=68 and a!=b else "#171326")
        self.pair_detail(*self.last_pair)
        for b in self.relation_buttons:
            b.configure(state="disabled" if self.busy or self.last_pair[0]==self.last_pair[1] else "normal")
    def cell_click(self,e):
        if not getattr(self,"hit",None):return
        r,c,n,m,l,t,w,h=self.hit
        x,y=self.heat.canvasx(e.x),self.heat.canvasy(e.y)
        if not (l<=x<l+m*w and t<=y<t+n*h):return
        self.last_pair=(r+int((y-t)//h),c+int((x-l)//w));self.draw_matrix()
    def pair_detail(self,i,j):
        a,b=self.current.files[i],self.current.files[j]
        if i==j:self.put(self.pair,a.name+"   ·   자기 자신과의 유사도 1.00");return
        s=self.current;v=compare(s,i,j,details=True)
        key=tuple(sorted((a.uid,b.uid)));rel=next((k for x,y,k in s.rules.rules.relations if (x,y)==key),None)
        rule={"must":"같은 그룹","cannot":"다른 그룹"}.get(rel,"직접 지정 없음")
        course={1:"일치",-1:"서로 다름",0:"비교 단서 없음"}[v['course']]
        scores=f"1차 {s.primary[i][j]/100:.2f}   →   최종 {s.matrix[i][j]/100:.2f}"
        if v["source_page"]:scores+="    ·    같은 출처 페이지"
        if v["task"]:scores+="    ·    반복된 작업명 "+s.task_prefixes[i]
        if s.matrix[i][j]!=s.primary[i][j]:
            sources=", ".join(f.name for f in (a,b) if f.index in s.extras)
            if sources:scores+=f"    ·    {sources} 본문 반영"
        self.put(self.pair,f"{a.name}   ↔   {b.name}\n{scores}\n파일명 단어 {v['literal']:.2f}   ·   의미 {v['semantic']:.2f}   ·   문자열 {v['string']:.2f}   ·   일반 문맥 {v['context']:.2f}\n강의 출처   {course}    /    사용자 관계   {rule}")
        self.pair.tag_configure("score",font=font(10,True),foreground=TEAL)
        self.pair.tag_add("score","2.0","2.end")
    def fill_flow(self):
        s=self.current;n=len(s.files)
        sections=[
            (f"1   스캔과 특징 추출   ·   파일 {n}개","원본 파일명과 정규화된 이름을 함께 보존합니다. 주차·순번·역할·버전을 나누고 메타데이터와 남아 있는 다운로드 출처를 읽습니다."),
            (f"2   관련도와 유사도 행렬   ·   {n*(n-1)//2:,}쌍","파일명 TF-IDF, 학술 용어 간 의미 관계, 문자열의 겹침을 계산합니다. 순번·시각·위치 같은 문맥은 이름 근거를 보완합니다."),
            ("3   계층 클러스터링","완전 연결 방식으로 그룹 간 가장 약한 연결이 0.60 이상인 동안 병합합니다. 사용자가 저장한 같은 그룹·다른 그룹 관계를 반영합니다."),
            (f"4   불확실성 탐지   ·   중간 {len(s.medium)}개","가장 가까운 그룹과 차점 그룹 간 차이, 가까운 이웃, 그룹 내부 평균을 함께 평가합니다. 높은 신뢰도의 파일은 본문을 열지 않습니다."),
            (f"5   선택적 추가 분석   ·   {'켜짐' if s.deep else '꺼짐'}",f"중간 등급 중 {len(s.attempted)}개에 발췌를 시도했고 {s.tried}개에서 텍스트를 얻었습니다. PDF는 제목과 첫 페이지, DOCX는 제목과 앞부분, TXT·MD는 앞부분을 사용합니다. HWP는 이름과 문맥으로 처리합니다."),
            (f"6   그룹 재계산과 검토   ·   추가 추천 {s.rescued}개",f"발췌 단서를 얻은 파일의 행·열만 갱신하고 확실한 그룹에 대해 다시 판단합니다. 최종 미분류 {sum(f.group is None for f in s.files)}개. ‘그룹 편집’ 또는 행렬에서 수정한 결정은 이 PC에 저장됩니다."),
            ("이번 실행",f"스캔·분석 {s.ms:,}ms   ·   읽을 수 없거나 제외된 항목 {s.skipped}개")]
        self.flow_summary.configure(text=f"분석 결과   ·   {n:,}개 파일   ·   과목명용 표지 확인 {sum(f.course_cover_checked for f in s.files)}개")
        self.flow.configure(state="normal");self.flow.delete("1.0","end")
        for h,b in sections:self.flow.insert("end",h+"\n","h");self.flow.insert("end",b+"\n\n")
        self.flow.configure(state="disabled")
    def popup(self,title,prompt,text,confirm=False,open_folder=None,confirm_text="확인 후 실행"):
        d=tk.Toplevel(self.w,bg=WHITE,width=self.px(650),height=self.px(360))
        d.withdraw()
        d.title(title)
        d.transient(self.w)
        d.minsize(self.px(430),self.px(260))
        d.grid_propagate(False)
        d.columnconfigure(0,weight=1)
        d.rowconfigure(1,weight=1)
        heading=label(d,prompt,12,True,INK,wraplength=self.px(605))
        heading.grid(row=0,column=0,sticky="ew",padx=self.px(15),pady=self.px(10))
        heading.bind("<Configure>",lambda event:heading.configure(wraplength=max(1,event.width)))
        area=tk.Frame(d,bg=WHITE)
        area.grid(row=1,column=0,sticky="nsew",padx=self.px(15))
        area.columnconfigure(0,weight=1)
        area.rowconfigure(0,weight=1)
        body=tk.Text(area,width=1,height=1,wrap="word",relief="flat",bg=BG,font=font(10),
                     padx=self.px(6),pady=self.px(4))
        body.grid(row=0,column=0,sticky="nsew")
        scrollbar(area,body,"vertical",0,1)
        self.put(body,text)

        accepted=False
        def accept():
            nonlocal accepted
            accepted=True
            d.destroy()
        bar=tk.Frame(d,bg=WHITE)
        bar.grid(row=2,column=0,sticky="ew",padx=self.px(15),pady=self.px(10))
        button(bar,confirm_text if confirm else "닫기",accept,True).pack(side="left")
        if confirm:button(bar,"취소",d.destroy).pack(side="left",padx=self.px(6))
        if open_folder:
            def open_result():
                try:os.startfile(str(open_folder))
                except OSError as error:messagebox.showerror("다운로드 폴더",str(error),parent=d)
            button(bar,"다운로드 폴더 열기",open_result).pack(side="right")
        d.bind("<Escape>",lambda e:d.destroy())
        d.tk.call("tk::PlaceWindow",str(d),"widget",str(self.w))
        d.grab_set()
        d.focus_set()
        self.w.wait_window(d)
        return accepted
    def selected_files(self):
        checked=[f for f in self.visible() if f.index in self.checked]
        return checked or [self.current.files[int(i)] for i in self.tree.selection()]
    def edit_menu(self):
        menu=tk.Menu(self.w,tearoff=False,font=font(10))
        for title,cmd in (("다른 그룹으로 이동…",self.assign),("새 그룹 만들기…",self.create_group),("두 그룹 병합…",self.merge_group),("체크한 파일로 그룹 분리…",self.split_group),("그룹 이름 변경…",self.rename_group)):
            menu.add_command(label=title,command=cmd)
        menu.add_separator()
        for kind,title in (("must","체크한 두 파일 · 같은 그룹"),("cannot","체크한 두 파일 · 다른 그룹"),("clear","체크한 두 파일 · 관계 해제")):
            menu.add_command(label=title,command=lambda k=kind:self.relation(k))
        try:menu.tk_popup(self.assign_btn.winfo_rootx(),self.assign_btn.winfo_rooty()-menu.winfo_reqheight())
        finally:menu.grab_release()
    def edit(self,fn,*args,**kwargs):
        if self.busy:return
        try:
            try:fn(self.current,*args,**kwargs)
            except feedback.CourseConflict as conflict:
                if not messagebox.askyesno("강좌 출처 확인",str(conflict),parent=self.w,default="no"):return
                fn(self.current,*args,**kwargs,allow_cross_course=True)
        except (ValueError,OSError,sqlite3.Error) as e:
            messagebox.showinfo("그룹 편집",str(e),parent=self.w);return
        self.analyze()
    def choose(self,title,groups,callback,allow_hold=False):
        choices=([None] if allow_hold else [])+list(groups)
        if not choices:
            messagebox.showinfo(title,"선택할 다른 그룹이 없습니다.",parent=self.w);return
        d=tk.Toplevel(self.w);d.title(title);d.transient(self.w);d.configure(bg=WHITE,padx=18,pady=14)
        label(d,title,11,True).pack(anchor="w",pady=(0,8))
        options=["미분류" if g is None else f"{g.title}   ({len(g.members)}개)" for g in choices]
        cb=ttk.Combobox(d,state="readonly",values=options,width=36);cb.current(0);cb.pack()
        def apply():
            chosen=choices[cb.current()];d.destroy();callback(chosen)
        button(d,"적용",apply,True).pack(anchor="e",pady=(10,0));d.grab_set()
    def active_group(self):
        if hasattr(self.scope,"members"):return self.scope
        selected=self.selected_files()
        return selected[0].group if selected else None
    def assign(self):
        fs=self.selected_files()
        if fs:self.choose("파일을 넣을 그룹",self.current.groups,lambda g:self.edit(feedback.assign,fs,g),True)
    def create_group(self):
        fs=self.selected_files()
        if fs:
            title=simpledialog.askstring("새 그룹","그룹 이름",parent=self.w)
            if title:self.edit(feedback.create,fs,title)
    def merge_group(self):
        g=self.active_group()
        if not g:messagebox.showinfo("그룹 병합","왼쪽에서 병합할 그룹을 선택하세요.",parent=self.w);return
        self.choose(f"‘{g.title}’ 그룹을 합칠 대상",[t for t in self.current.groups if t is not g],lambda t:self.edit(feedback.merge,g,t))
    def split_group(self):
        fs=self.selected_files();g=self.active_group()
        if not g or not set(fs)<set(g.members) or not fs:
            messagebox.showinfo("그룹 분리","한 그룹에서 분리할 파일 일부를 체크하세요.",parent=self.w);return
        title=simpledialog.askstring("그룹 분리","분리할 그룹의 이름",parent=self.w)
        if title:self.edit(feedback.split,g,fs,title)
    def rename_group(self):
        g=self.active_group()
        if not g:messagebox.showinfo("이름 변경","왼쪽에서 이름을 바꿀 그룹을 선택하세요.",parent=self.w);return
        title=simpledialog.askstring("이름 변경","새 그룹 이름",initialvalue=g.title,parent=self.w)
        if title:self.edit(feedback.rename,g,title)

    def review_course_title(self):
        group=self.scope
        if self.busy or not hasattr(group,"members"):return
        if group.title_kind in {"lms","cover","manual","confirmed"}:
            self.confirm_course_title(group,group.title,group.title_note)
            return
        self.status.configure(text="강의소개 표지 확인 중")
        self.work("course_title",lambda:(group,*course_cover(group.members)))

    def confirm_course_title(self,group,candidate,source):
        self.stats()
        scope_note=("같은 강좌 출처가 확인된 그룹에 이 이름을 사용합니다."
                    if group_scope(group.members) else "이 그룹에 사용할 이름입니다.")
        title=simpledialog.askstring("파일명 변경",f"{source}\n{scope_note}\n\n과목명",
                                     initialvalue=candidate or group.title,parent=self.w)
        if title and title.strip():self.edit(feedback.set_course_title,group,title)
    def relation(self,kind):
        if self.busy or self.current is None:return
        if self.view=="matrix" and self.last_pair:
            fs=[self.current.files[i] for i in self.last_pair]
        else:fs=self.selected_files()
        if len(fs)!=2 or fs[0] is fs[1]:
            messagebox.showinfo("파일 관계","서로 다른 파일 두 개를 체크하거나 행렬에서 두 파일의 셀을 선택하세요.",parent=self.w);return
        self.edit(feedback.save_edit,relation=(fs[0],fs[1],kind))
    def organize_groups(self):
        if self.busy or not self.current or self.scope=="hold":return
        study=self.current
        selected=self.scope if hasattr(self.scope,"members") else None
        plan=storage.plan_group_folders(study,selected)
        pending=[item for item in plan if not item.skip]
        folders={item.target.parent for item in pending}
        lines=[f"정리 위치   {study.root}"]
        for directory,items in groupby(plan,key=lambda item:item.target.parent):
            items=list(items)
            lines.extend(("",f"▸ {directory.name}"))
            lines.append("    "+items[0].file.group.title_note)
            for item in items:
                source=item.file.path.relative_to(study.root)
                lines.append(f"    {source}" + (f"    ·    건너뜀 ({item.skip})" if item.skip else ""))
        skipped=len(plan)-len(pending)
        summary=(f"{len(pending)}개 파일을 그룹 폴더 {len(folders)}개로 이동합니다."
                 if pending else "이동할 파일이 없습니다.")
        if skipped:summary+=f"  건너뜀 {skipped}개"
        if self.popup("그룹별 폴더 정리 미리보기",summary,"\n".join(lines),confirm=bool(pending),
                      confirm_text=f"{len(pending)}개 파일 이동") and pending:
            self.status.configure(text="그룹별 폴더로 파일 이동 중")
            self.work("organize",lambda:storage.move_files(plan,study.root))

    def move(self):
        picked=[f for f in self.visible() if f.index in self.checked]
        if not picked:return
        default=self.path.parent
        dest=filedialog.askdirectory(parent=self.w,title="체크한 파일을 옮길 목적지",initialdir=str(default))
        if not dest:return
        if self.popup("이동 전 확인",f"{len(picked)}개 파일을 아래 폴더로 이동합니다.",str(dest)+"\n\n"+"\n".join(str(f.path) for f in picked),True):
            self.status.config(text="파일 이동 중");self.work("move",lambda:storage.move(picked,dest))
    def undo(self):
        try:path,rows=storage.latest()
        except (OSError,ValueError) as e:messagebox.showerror("이동 기록",str(e),parent=self.w);return
        if not path:messagebox.showinfo("이동 되돌리기","되돌릴 이동 기록이 없습니다.",parent=self.w);return
        if self.popup("최근 이동 되돌리기","아래 파일을 원래 위치로 복원합니다.","\n\n".join(r["dst"]+"\n→ "+r["src"] for r in rows if storage.pending(r)),True):
            self.status.config(text="파일 복원 중");self.work("undo",lambda:storage.undo(path))

if __name__=="__main__":
    window=create_window();App(window);window.mainloop()
