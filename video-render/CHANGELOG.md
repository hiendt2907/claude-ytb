# Changelog

## Unreleased

- Cho huy rieng 1 doan cat da chon trong Review & cat: bam vao dung khoi mau do tren timeline se xoa rieng doan do (stopPropagation de khong bi hieu nham thanh keo vung moi), thay vi truoc day chi co "Xoa vung cat" xoa toan bo.
- Fix dong goi macOS (build & test that qua dist/Video Render.app):
  - desktop.py check "server da chay" truoc day chi xem status < 500, nen
    neu may user co san app khac dang dung port 8000 se bi nham la chinh
    minh da chay va khong khoi dong server that. Gio verify dung danh tinh
    qua /api/edit-profiles, va tu tim port trong (8000-8019, roi random)
    neu port mac dinh bi chiem boi app khac.
  - _ensure_stdio() truoc day chi tao thu muc log khi sys.stdout/stderr la
    None, nhung PyInstaller --windowed khong dam bao dieu do (co ban tro
    devnull thay vi None) nen app crash ngay luc khoi dong voi
    FileNotFoundError, khong co log nao de biet ly do. Gio luon tao thu
    muc truoc.
  - App dong goi chay voi CWD khong xac dinh (thuong la '/', read-only),
    trong khi output_dir mac dinh cua Web UI la duong dan tuong doi
    "output" -> render luon bao "Read-only file system" neu user khong tu
    chon thu muc output. Gio desktop.py tu chdir ve ~/Movies/Video Render
    (macOS) / ~/Videos/Video Render (Windows) truoc khi khoi dong server.
  - ffmpeg bundle qua static-ffmpeg la ban 7.0, trong khi ffmpeg dev
    (Homebrew) la 8.1.1 — filter normalize_video_filter() co
    setpts=N/(FPS*TB) du thua sau fps=, gay loi "constant frame rate 1/0
    invalid" trong xfade tren ffmpeg 7.0 (8.1.1 khong loi nen khong phat
    hien duoc luc dev). Bo setpts du thua, chi con fps=+format+setsar da
    du de dam bao CFR dung.
  - Ca 4 loi deu chi xuat hien khi chay dung app da build/dong goi, khong
    loi nao lo ra khi chi chay qua `.venv/bin/video-render` (dev mode) —
    xac nhan can build va launch app that truoc khi coi la "da dong goi
    xong", khong chi tin vao script build chay khong loi.

- Timeline Review & cat gio snap moi vi tri keo/hover ve dung luoi khung hinh 60fps (1/60s) de can chinh diem cat chinh xac tung khung, khong bi lech so thuc. Rê chuot (chua can bam keo) cung tua preview video theo dung khung tai vi tri con tro, khong chi luc dang keo. Filmstrip tinh cung tang mat do khung hinh hon.
- Timeline trong modal Review & cat gio hien filmstrip khung hinh that cua video (canvas + video an de seek/trich frame client-side, cover-fit khong meo hinh), thay vi chi hien luoi ke thang mau xam. Frame render tang dan tu trai qua phai khi mo modal.
- Timeline trong modal Review & cat cao gap doi (52px -> 110px) de keo chinh xac hon. Khi keo chon vung can bo, video tu tua theo con tro va mo dan (dim overlay + nhan "Doan nay se bi cat") de thay ngay dung doan sap cat la doan nao truoc khi tha chuot.
- Tach UI thanh 2 phase ro rang: Phase 1 (render tho) chi con progress bar + log; render xong tu dong chuyen sang trang Ket qua dang gallery, xem preview inline tung video, roi user tu chon Edit trong app (Review & cat, cap nhat tai cho trong gallery, khong tao card moi) hoac Tai ve dung app khac. Render lai video loi chat luong cung cap nhat tai cho. Chi trong phien hien tai, chua persist qua refresh/restart.
- Smart Suggestion doc do chuyen dong that tren khung hinh (ffmpeg signalstats YDIF, lay mau 5s dau/canh) thay vi chi doan theo ten thu muc; roi ve heuristic cau truc cu (so canh/so clip) khi khong do duoc hoac chuyen dong o muc trung binh.
- Lo tuy chinh transition/motion (do dai chuyen canh/clip, do manh zoom, pan ngang/doc, toc do pan, do dai fade cuoi) ra UI o buoc "Kieu dung": user co the keo slider de ghi de tung gia tri cua profile dang chon, thay vi chi chon 1 profile co dinh.

## 0.3.0 - 2026-07-08

- Bat dau UX foundation cho v0.3: giu mac dinh `App tu chon`, nhung them duong `Tu chon clip` de user nhap nhanh format `1.1, 2.1, 3.2` khi can kiem soat chinh xac.
- Manual plan chap nhan ca format ngan moi dong la mot video va format cu `video 1: ...`.
- Them API preview/validate manual plan truoc khi preview/render, bao loi theo dong de user sua nhanh.
- Them control UI `Kiem tra danh sach` de hien video/canh/clip app se dung truoc khi render.
- Scan video nguon hien mapping clip ref -> ten file, va them nut tao mau danh sach clip tu scenes hien co.
- Job render luu render plan metadata cho tung output: profile, duration mode, scene duration, group clips, selected segments va output path.
- Smart Trim co the chon nhieu segment khong overlap trong cung mot clip de fit duration tot hon.
- Preview dai hon lay mau dau/giua/cuoi thay vi chi lay 4 canh dau.
- Quality gate canh bao khi do dai tieng va hinh lech nhau.
- Them profile `smooth_retry` rieng cho flow render lai muot hon.
- Them endpoint render lai dung tung output loi bang render plan da luu, khong sinh bien the random moi.
- Them quick adjustment trong preview: muot hon, nhanh hon, it zoom hon, giu canh lau hon, doi doan khac.
- Quick adjustment trong preview render lai ban xem thu ngay trong popup; chi cap nhat cau hinh chinh khi user bam `Dung kieu nay`.
- Them Smart Suggestion opt-in sau scan: app de xuat profile dua tren so canh, so clip, aspect ratio, mode manual/random; user bam `Dung goi y` thi moi ap dung.
- Cap nhat `docs/V0.3_UPGRADE_PLAN.md` thanh release plan day du cho UX, Smart Trim 2, quality gate, retry dung video loi, preview tot hon, performance va release gate `0.3.0`.

## 0.2.0 - 2026-07-08

- Chot lai san pham thanh tool render-only cho KOL/KOC/affiliate.
- Them auto-assembler random/manual, dam bao coverage clip nguon trong batch.
- Them Smart Trim MVP de tu chon doan dep trong clip truoc khi render.
- Them auto-edit profiles, motion pan/zoom lien tuc, xfade giua clip va giua canh.
- Them web UI guided 3 buoc, preview popup, estimate, templates, quality summary.
- Them desktop/packaging entrypoint va co che resolve ffmpeg bundled.

## 0.1.0 - Initial

- Nen tang FastAPI + CLI cho viec ghep scene folders va voice track thanh output video.
