import flet as ft
import sqlite3
import datetime
import calendar
import json


# ==========================================
# メイン
# ==========================================

def main(page: ft.Page):

    # ==========================================
    # ページ設定
    # ==========================================

    page.title = "BandMatch"
    page.bgcolor = "#FFFFE0"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    # ==========================================
    # データベース作成
    # ==========================================

    conn = sqlite3.connect("bandmatch.db")

    # ------------------------------------------
    # usersテーブル
    # grade： 08=1年生 / 07=2年生 / 06=3年生(執行代) / 05=4年生
    # ------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grade TEXT,
            name TEXT,
            nickname TEXT,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0
        )
    """)

    for column_name, column_type in [
        ("grade", "TEXT"),
        ("name", "TEXT"),
        ("nickname", "TEXT"),
        # ★追加：管理者（パートリーダー）フラグ
        ("is_admin", "INTEGER NOT NULL DEFAULT 0"),
    ]:

        try:
            conn.execute(
                f"ALTER TABLE users ADD COLUMN "
                f"{column_name} {column_type}"
            )
        except sqlite3.OperationalError:
            pass

    # ------------------------------------------
    # practicesテーブル
    # ------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS practices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            location TEXT,
            content TEXT
        )
    """)

    # ------------------------------------------
    # attendanceテーブル
    # ------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            practice_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(practice_id, user_id)
        )
    """)

    # ------------------------------------------
    # ★追加：eventsテーブル
    # type: 'teiki'(定期演奏会) / 'komaba'(駒場祭) / 'satsuki'(五月祭)
    # ------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL UNIQUE
        )
    """)

    # ------------------------------------------
    # ★追加：event_partsテーブル
    # 「第1部」「メイン」など、曲が属する分類
    # ここを画面に直書きせず、曲側にラベルを持たせる設計
    # ------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS event_parts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            sort_order INTEGER NOT NULL
        )
    """)

    # ------------------------------------------
    # ★追加：songsテーブル
    # ------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_part_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            sort_order INTEGER NOT NULL
        )
    """)

    # ------------------------------------------
    # ★追加：song_instrumentsテーブル
    # 曲ごとのパート編成（楽器・分割・定員）
    # divisions / capacity_per_division はJSON配列で保存
    # 例: divisions=["1st","2nd","Picc"] capacity=[3,3,1]
    # ------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS song_instruments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id INTEGER NOT NULL,
            instrument_name TEXT NOT NULL,
            divisions TEXT NOT NULL,
            capacity_per_division TEXT NOT NULL
        )
    """)

    # ------------------------------------------
    # ★追加：part_preferencesテーブル
    # 第1〜第4希望（rank=1〜4）
    # ------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS part_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            rank INTEGER NOT NULL,
            instrument_name TEXT NOT NULL,
            division TEXT NOT NULL,
            UNIQUE(song_id, user_id, rank)
        )
    """)

    # ------------------------------------------
    # ★追加：part_assignmentsテーブル（確定結果）
    # ------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS part_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            instrument_name TEXT,
            division TEXT,
            UNIQUE(song_id, user_id)
        )
    """)

    # ------------------------------------------
    # ★追加：camp_attendanceテーブル（合宿の出欠）
    # camp_type: 'spring'(春合宿) / 'summer'(夏合宿)
    # ------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS camp_attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camp_type TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            attending INTEGER NOT NULL,
            UNIQUE(camp_type, user_id)
        )
    """)

    conn.commit()
    conn.close()

    # ==========================================
    # 学年コード ⇔ 表示名
    # ==========================================

    GRADE_LABELS = {
        "08": "1年生",
        "07": "2年生",
        "06": "3年生",
        "05": "4年生",
    }

    # ------------------------------------------
    # ★追加：学年ごとのパート割り振り優先度
    # 執行代である06(3年生)を最優先
    # ------------------------------------------

    GRADE_WEIGHT = {
        "06": 4,
        "05": 3,
        "07": 2,
        "08": 1,
    }

    # ==========================================
    # ★追加：イベント関連の定数
    # ==========================================

    EVENT_TYPE_LABELS = {
        "teiki": "定期演奏会",
        "komaba": "駒場祭",
        "satsuki": "五月祭",
    }

    # 各イベントがどちらの合宿に対応するか
    EVENT_TYPE_CAMP = {
        "teiki": "summer",
        "komaba": "summer",
        "satsuki": "spring",
    }

    CAMP_LABELS = {
        "spring": "春合宿",
        "summer": "夏合宿",
    }

    def default_categories(event_type):
        # 定期演奏会は「第1部/第2部/第3部/アンコール」
        # 駒場祭・五月祭は「通常(番号付き)/メイン/サブメイン/アンコール」
        if event_type == "teiki":
            return ["第1部", "第2部", "第3部", "アンコール"]
        else:
            return ["通常", "メイン", "サブメイン", "アンコール"]

    # ------------------------------------------
    # ★追加：3つのイベントを最初に1回だけ作成
    # ------------------------------------------

    def ensure_default_events():

        conn = sqlite3.connect("bandmatch.db")

        for ev_type, ev_name in EVENT_TYPE_LABELS.items():

            row = conn.execute(
                "SELECT id FROM events WHERE type=?",
                (ev_type,),
            ).fetchone()

            if row is None:

                cur = conn.execute(
                    "INSERT INTO events (name, type) VALUES (?, ?)",
                    (ev_name, ev_type),
                )

                event_id = cur.lastrowid

                for i, label in enumerate(default_categories(ev_type)):
                    conn.execute(
                        """
                        INSERT INTO event_parts
                        (event_id, label, sort_order)
                        VALUES (?, ?, ?)
                        """,
                        (event_id, label, i),
                    )

            else:

                # ★追加：既存イベントに、後から追加された
                # デフォルト分類（第3部・アンコールなど）が
                # まだ無ければ追加する
                event_id = row[0]

                existing_labels = [
                    r[0]
                    for r in conn.execute(
                        """
                        SELECT label FROM event_parts
                        WHERE event_id=?
                        """,
                        (event_id,),
                    ).fetchall()
                ]

                max_order = conn.execute(
                    """
                    SELECT COALESCE(MAX(sort_order), -1)
                    FROM event_parts
                    WHERE event_id=?
                    """,
                    (event_id,),
                ).fetchone()[0]

                for label in default_categories(ev_type):

                    if label not in existing_labels:

                        max_order += 1

                        conn.execute(
                            """
                            INSERT INTO event_parts
                            (event_id, label, sort_order)
                            VALUES (?, ?, ?)
                            """,
                            (event_id, label, max_order),
                        )

        conn.commit()
        conn.close()

    ensure_default_events()

    # ==========================================
    # ★追加：管理者アカウントの自動作成（初回のみ）
    # 部員が1人も登録されていない状態でアプリを
    # 初めて起動したときだけ、テスト管理者アカウントを
    # 1つ作成する（動作確認用・以後は管理者管理画面で
    # 新しい管理者を追加していく）
    # ==========================================

    def ensure_bootstrap_admin():

        conn = sqlite3.connect("bandmatch.db")

        user_count = conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        if user_count == 0:

            conn.execute(
                """
                INSERT INTO users
                (grade, name, nickname, email, password, is_admin)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    "06",
                    "テスト管理者",
                    "テスト管理者",
                    "test@example.com",
                    "1234",
                ),
            )

            conn.commit()

        conn.close()

    ensure_bootstrap_admin()

    # ==========================================
    # ★変更：現在ログインしているユーザー（セッション）
    # ログイン画面で実際にusersテーブルと照合して
    # ここに入れる。管理者かどうかもここで判定する
    # ==========================================

    current_user_id = None
    current_user_name = ""
    is_admin = False

    # ==========================================
    # ログイン画面
    # ==========================================

    def show_login():

        page.clean()

        title = ft.Text(
            "🎺 BandMatch",
            size=32,
            weight=ft.FontWeight.BOLD,
        )

        email = ft.TextField(
            label="メールアドレス",
            width=350,
        )

        password = ft.TextField(
            label="パスワード",
            password=True,
            can_reveal_password=True,
            width=350,
        )

        message = ft.Text(
            "",
            size=14,
        )

        def login_click(e):

            nonlocal current_user_id, current_user_name, is_admin

            if email.value == "" and password.value == "":
                message.value = (
                    "メールアドレスとパスワードを入力してください！"
                )
                message.color = ft.Colors.RED

            elif email.value == "":
                message.value = (
                    "メールアドレスを入力してください！"
                )
                message.color = ft.Colors.RED

            elif password.value == "":
                message.value = (
                    "パスワードを入力してください！"
                )
                message.color = ft.Colors.RED

            else:

                conn = sqlite3.connect("bandmatch.db")

                row = conn.execute(
                    """
                    SELECT id, nickname, email, is_admin
                    FROM users
                    WHERE email=? AND password=?
                    """,
                    (email.value, password.value),
                ).fetchone()

                conn.close()

                if row:

                    current_user_id = row[0]
                    current_user_name = row[1] if row[1] else row[2]
                    is_admin = bool(row[3])

                    show_home()
                    return

                else:
                    message.value = (
                        "メールアドレスまたはパスワードが違います"
                    )
                    message.color = ft.Colors.RED

            page.update()

        login_button = ft.ElevatedButton(
            "ログイン",
            width=350,
            height=50,
            on_click=login_click,
        )

        signup_button = ft.OutlinedButton(
            "新規登録",
            width=350,
            height=50,
            on_click=show_signup,
        )

        page.add(
            ft.Column(
                controls=[
                    title,
                    email,
                    password,
                    message,
                    login_button,
                    signup_button,
                ],
                horizontal_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
                spacing=20,
            )
        )

    # ==========================================
    # 新規登録画面
    # ==========================================

    def show_signup():

        page.clean()

        title = ft.Text(
            "🎺 BandMatch",
            size=32,
            weight=ft.FontWeight.BOLD,
        )

        signup_text = ft.Text(
            "アカウント新規作成",
            size=24,
        )

        grade_dropdown = ft.Dropdown(
            label="学年",
            width=350,
            options=[
                ft.dropdown.Option(
                    key=code,
                    text=GRADE_LABELS[code],
                )
                for code in ["08", "07", "06", "05"]
            ],
        )

        name_field = ft.TextField(
            label="氏名",
            hint_text="山田 太郎",
            width=350,
        )

        nickname_field = ft.TextField(
            label="あだ名",
            hint_text="たろちゃん",
            width=350,
        )

        signup_email = ft.TextField(
            label="メールアドレス",
            width=350,
        )

        signup_password = ft.TextField(
            label="パスワード",
            password=True,
            can_reveal_password=True,
            width=350,
        )

        signup_password_confirm = ft.TextField(
            label="パスワード（確認）",
            password=True,
            can_reveal_password=True,
            width=350,
        )

        signup_message = ft.Text(
            "",
            size=14,
        )

        def create_account(e):

            if grade_dropdown.value is None:
                signup_message.value = (
                    "学年を選択してください！"
                )
                signup_message.color = ft.Colors.RED

            elif name_field.value == "":
                signup_message.value = (
                    "氏名を入力してください！"
                )
                signup_message.color = ft.Colors.RED

            elif nickname_field.value == "":
                signup_message.value = (
                    "あだ名を入力してください！"
                )
                signup_message.color = ft.Colors.RED

            elif signup_email.value == "":
                signup_message.value = (
                    "メールアドレスを入力してください！"
                )
                signup_message.color = ft.Colors.RED

            elif signup_password.value == "":
                signup_message.value = (
                    "パスワードを入力してください！"
                )
                signup_message.color = ft.Colors.RED

            elif signup_password_confirm.value == "":
                signup_message.value = (
                    "パスワード（確認）を入力してください！"
                )
                signup_message.color = ft.Colors.RED

            elif (
                signup_password.value
                != signup_password_confirm.value
            ):
                signup_message.value = (
                    "パスワードが一致しません！"
                )
                signup_message.color = ft.Colors.RED

            else:

                try:

                    conn = sqlite3.connect("bandmatch.db")

                    conn.execute(
                        """
                        INSERT INTO users
                        (
                            grade,
                            name,
                            nickname,
                            email,
                            password
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            grade_dropdown.value,
                            name_field.value,
                            nickname_field.value,
                            signup_email.value,
                            signup_password.value,
                        ),
                    )

                    conn.commit()
                    conn.close()

                    signup_message.value = (
                        "アカウントを作成しました！"
                    )
                    signup_message.color = ft.Colors.GREEN

                except sqlite3.IntegrityError:

                    signup_message.value = (
                        "このメールアドレスは"
                        "既に登録されています！"
                    )
                    signup_message.color = ft.Colors.RED

            page.update()

        create_button = ft.ElevatedButton(
            "アカウント作成",
            width=350,
            height=50,
            on_click=create_account,
        )

        back_button = ft.OutlinedButton(
            "ログインに戻る",
            width=350,
            height=50,
            on_click=lambda e: show_login(),
        )

        page.add(
            ft.Column(
                controls=[
                    title,
                    signup_text,
                    grade_dropdown,
                    name_field,
                    nickname_field,
                    signup_email,
                    signup_password,
                    signup_password_confirm,
                    signup_message,
                    create_button,
                    back_button,
                ],
                horizontal_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
                spacing=20,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    # ==========================================
    # 管理者画面（練習日登録）
    # ==========================================

    def show_admin():

        if not is_admin:
            show_home()
            return

        page.clean()

        admin_title = ft.Text(
            "🎺 BandMatch",
            size=32,
            weight=ft.FontWeight.BOLD,
        )

        admin_text = ft.Text(
            "練習日を登録",
            size=24,
        )

        date_field = ft.TextField(
            label="練習日",
            hint_text="2026/08/20",
            width=350,
        )

        start_time_field = ft.TextField(
            label="開始時間",
            hint_text="18:00",
            width=350,
        )

        end_time_field = ft.TextField(
            label="終了時間",
            hint_text="21:00",
            width=350,
        )

        location_field = ft.TextField(
            label="場所",
            hint_text="○○音楽室",
            width=350,
        )

        content_field = ft.TextField(
            label="練習内容",
            hint_text="コンクール曲の合奏",
            width=350,
            multiline=True,
            min_lines=3,
        )

        message = ft.Text(
            "",
            size=14,
        )

        def register_practice(e):

            if date_field.value == "":
                message.value = (
                    "練習日を入力してください！"
                )
                message.color = ft.Colors.RED

            elif start_time_field.value == "":
                message.value = (
                    "開始時間を入力してください！"
                )
                message.color = ft.Colors.RED

            elif end_time_field.value == "":
                message.value = (
                    "終了時間を入力してください！"
                )
                message.color = ft.Colors.RED

            else:

                conn = sqlite3.connect("bandmatch.db")

                conn.execute(
                    """
                    INSERT INTO practices
                    (
                        date,
                        start_time,
                        end_time,
                        location,
                        content
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        date_field.value,
                        start_time_field.value,
                        end_time_field.value,
                        location_field.value,
                        content_field.value,
                    ),
                )

                conn.commit()
                conn.close()

                message.value = (
                    "練習日を登録しました！🎺"
                )
                message.color = ft.Colors.GREEN

            page.update()

        register_button = ft.ElevatedButton(
            "練習日を登録",
            width=350,
            height=50,
            on_click=register_practice,
        )

        back_button = ft.OutlinedButton(
            "ホームに戻る",
            width=350,
            height=50,
            on_click=lambda e: show_home(),
        )

        page.add(
            ft.Column(
                controls=[
                    admin_title,
                    admin_text,
                    date_field,
                    start_time_field,
                    end_time_field,
                    location_field,
                    content_field,
                    message,
                    register_button,
                    back_button,
                ],
                horizontal_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
                spacing=15,
            )
        )

    # ==========================================
    # ★追加：合宿の出欠設定（ユーザー本人のみ）
    # ==========================================

    def show_camp_survey():

        page.clean()

        conn = sqlite3.connect("bandmatch.db")

        existing = conn.execute(
            """
            SELECT camp_type, attending
            FROM camp_attendance
            WHERE user_id=?
            """,
            (current_user_id,),
        ).fetchall()

        conn.close()

        existing_map = {c: a for c, a in existing}

        controls = [
            ft.Text(
                "🏕 合宿の出欠設定",
                size=22,
                weight=ft.FontWeight.BOLD,
            ),
            ft.Text(
                "※来られる合宿はONにしてください。"
                "自動パート決めの際に考慮されます",
                size=12,
                color=ft.Colors.GREY,
            ),
        ]

        switches = {}

        for camp_type in ["spring", "summer"]:

            sw = ft.Switch(
                label=f"{CAMP_LABELS[camp_type]}　（来るならON）",
                value=bool(existing_map.get(camp_type, 0)),
            )

            switches[camp_type] = sw
            controls.append(sw)

        message = ft.Text("", size=14)

        def save(e):

            conn = sqlite3.connect("bandmatch.db")

            for camp_type, sw in switches.items():

                existing_row = conn.execute(
                    """
                    SELECT id FROM camp_attendance
                    WHERE camp_type=? AND user_id=?
                    """,
                    (camp_type, current_user_id),
                ).fetchone()

                value = 1 if sw.value else 0

                if existing_row:
                    conn.execute(
                        """
                        UPDATE camp_attendance
                        SET attending=?
                        WHERE camp_type=? AND user_id=?
                        """,
                        (value, camp_type, current_user_id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO camp_attendance
                        (camp_type, user_id, attending)
                        VALUES (?, ?, ?)
                        """,
                        (camp_type, current_user_id, value),
                    )

            conn.commit()
            conn.close()

            message.value = "保存しました！"
            message.color = ft.Colors.GREEN
            page.update()

        controls.append(
            ft.ElevatedButton(
                "保存する",
                width=350,
                height=50,
                on_click=save,
            )
        )

        controls.append(message)

        controls.append(
            ft.OutlinedButton(
                "ホームに戻る",
                width=350,
                height=50,
                on_click=lambda e: show_home(),
            )
        )

        page.add(
            ft.Column(
                controls=controls,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    # ==========================================
    # ★追加：合宿に誰が来るか一覧（管理者・閲覧のみ）
    # ==========================================

    def show_camp_admin_view():

        if not is_admin:
            show_home()
            return

        page.clean()

        conn = sqlite3.connect("bandmatch.db")

        users = conn.execute(
            "SELECT id, nickname, email FROM users ORDER BY id"
        ).fetchall()

        existing = conn.execute(
            "SELECT camp_type, user_id, attending FROM camp_attendance"
        ).fetchall()

        conn.close()

        existing_map = {(c, u): a for c, u, a in existing}

        controls = [
            ft.Text(
                "🏕 合宿に誰が来るか（管理者）",
                size=22,
                weight=ft.FontWeight.BOLD,
            ),
        ]

        for camp_type in ["spring", "summer"]:

            controls.append(
                ft.Text(
                    f"【{CAMP_LABELS[camp_type]}】",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                )
            )

            if not users:
                controls.append(
                    ft.Text("部員が登録されていません", size=13)
                )

            attending_names = []
            not_attending_names = []

            for user_id, nickname, email in users:

                name = nickname if nickname else email

                if existing_map.get((camp_type, user_id), 0):
                    attending_names.append(name)
                else:
                    not_attending_names.append(name)

            controls.append(
                ft.Text(
                    "来る：" + (
                        "、".join(attending_names)
                        if attending_names
                        else "（まだいません）"
                    ),
                    size=14,
                )
            )

            controls.append(
                ft.Text(
                    "来ない／未設定：" + (
                        "、".join(not_attending_names)
                        if not_attending_names
                        else "（なし）"
                    ),
                    size=14,
                    color=ft.Colors.GREY,
                )
            )

        controls.append(
            ft.OutlinedButton(
                "ホームに戻る",
                width=350,
                height=50,
                on_click=lambda e: show_home(),
            )
        )

        page.add(
            ft.Column(
                controls=controls,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    # ==========================================
    # ★追加：管理者管理（管理者の追加・削除）
    # 代替わりの際、新しい執行代を管理者にできる
    # ==========================================

    def show_admin_management():

        if not is_admin:
            show_home()
            return

        page.clean()

        conn = sqlite3.connect("bandmatch.db")

        users = conn.execute(
            """
            SELECT id, nickname, email, grade, is_admin
            FROM users
            ORDER BY id
            """
        ).fetchall()

        conn.close()

        controls = [
            ft.Text(
                "⚙ 管理者管理",
                size=22,
                weight=ft.FontWeight.BOLD,
            ),
            ft.Text(
                "※代替わりの際は、新しい執行代をONにしてください",
                size=12,
                color=ft.Colors.GREY,
            ),
        ]

        if not users:
            controls.append(
                ft.Text("部員が登録されていません", size=14)
            )

        switches = {}

        for user_id, nickname, email, grade, is_admin_flag in users:

            name = nickname if nickname else email
            grade_label = GRADE_LABELS.get(grade, "")

            sw = ft.Switch(
                label=f"{name}（{grade_label}）　管理者ならON",
                value=bool(is_admin_flag),
            )

            switches[user_id] = sw
            controls.append(sw)

        message = ft.Text("", size=14)

        def save(e):

            nonlocal is_admin

            conn = sqlite3.connect("bandmatch.db")

            for user_id, sw in switches.items():

                conn.execute(
                    "UPDATE users SET is_admin=? WHERE id=?",
                    (1 if sw.value else 0, user_id),
                )

            conn.commit()
            conn.close()

            # 自分自身の権限が変わった場合はセッションにも反映
            if current_user_id in switches:
                is_admin = bool(switches[current_user_id].value)

            message.value = "保存しました！"
            message.color = ft.Colors.GREEN
            page.update()

        controls.append(
            ft.ElevatedButton(
                "保存する",
                width=350,
                height=50,
                on_click=save,
            )
        )

        controls.append(message)

        controls.append(
            ft.OutlinedButton(
                "ホームに戻る",
                width=350,
                height=50,
                on_click=lambda e: show_home(),
            )
        )

        page.add(
            ft.Column(
                controls=controls,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    # ==========================================
    # ★追加：イベント一覧画面
    # ==========================================

    def show_events():

        page.clean()

        title = ft.Text(
            "🎪 イベント",
            size=32,
            weight=ft.FontWeight.BOLD,
        )

        buttons = []

        for ev_type, ev_name in EVENT_TYPE_LABELS.items():

            buttons.append(
                ft.ElevatedButton(
                    f"🎪 {ev_name} ▶",
                    width=350,
                    height=50,
                    on_click=(
                        lambda e, t=ev_type: show_event_detail(t)
                    ),
                )
            )

        back_button = ft.OutlinedButton(
            "ホームに戻る",
            width=350,
            height=50,
            on_click=lambda e: show_home(),
        )

        page.add(
            ft.Column(
                controls=[title, *buttons, back_button],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=20,
            )
        )

    # ==========================================
    # ★追加：イベント詳細（セトリ表示）画面
    # ==========================================

    def show_event_detail(event_type):

        page.clean()

        conn = sqlite3.connect("bandmatch.db")

        event = conn.execute(
            "SELECT id, name FROM events WHERE type=?",
            (event_type,),
        ).fetchone()

        event_id, event_name = event

        parts = conn.execute(
            """
            SELECT id, label
            FROM event_parts
            WHERE event_id=?
            ORDER BY sort_order
            """,
            (event_id,),
        ).fetchall()

        section_controls = []

        # 「通常」カテゴリの曲は 1. 2. 3. と通し番号で表示
        normal_song_number = 1

        for part_id, label in parts:

            songs = conn.execute(
                """
                SELECT id, title
                FROM songs
                WHERE event_part_id=?
                ORDER BY sort_order
                """,
                (part_id,),
            ).fetchall()

            # 「通常」は見出しを出さず番号だけで表示する
            if label != "通常":
                section_controls.append(
                    ft.Text(
                        f"【{label}】",
                        size=18,
                        weight=ft.FontWeight.BOLD,
                    )
                )

            if not songs:
                section_controls.append(
                    ft.Text(
                        "　（曲がまだ登録されていません）",
                        size=13,
                        color=ft.Colors.GREY,
                    )
                )

            for song_id, song_title in songs:

                if label == "通常":
                    display_text = (
                        f"{normal_song_number}. {song_title}"
                    )
                    normal_song_number += 1
                else:
                    display_text = f"・{song_title}"

                section_controls.append(
                    ft.TextButton(
                        display_text,
                        on_click=(
                            lambda e, sid=song_id:
                                show_song_detail(sid, event_type)
                        ),
                    )
                )

            if is_admin:
                section_controls.append(
                    ft.OutlinedButton(
                        "＋ 曲を追加（管理者）",
                        on_click=(
                            lambda e, pid=part_id:
                                show_add_song_dialog(pid, event_type)
                        ),
                    )
                )

            section_controls.append(ft.Divider())

        conn.close()

        title = ft.Text(
            f"🎪 {event_name}",
            size=28,
            weight=ft.FontWeight.BOLD,
        )

        back_button = ft.OutlinedButton(
            "イベント一覧に戻る",
            width=350,
            height=50,
            on_click=lambda e: show_events(),
        )

        page.add(
            ft.Column(
                controls=[title, *section_controls, back_button],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    # ==========================================
    # ★追加：曲を追加するダイアログ（管理者）
    # ==========================================

    def show_add_song_dialog(event_part_id, event_type):

        if not is_admin:
            show_home()
            return

        title_field = ft.TextField(
            label="曲名",
            width=350,
        )

        instrument_rows = []
        instrument_column = ft.Column(spacing=10)

        message = ft.Text("", size=13)

        def add_instrument_row(e=None):

            name_field = ft.TextField(
                label="楽器名",
                hint_text="Flute",
                width=160,
            )

            divisions_field = ft.TextField(
                label="分割:定員",
                hint_text="1st:3,2nd:3,Picc:1",
                width=220,
            )

            instrument_rows.append((name_field, divisions_field))

            instrument_column.controls.append(
                ft.Row(
                    [name_field, divisions_field],
                    spacing=10,
                )
            )

            page.update()

        add_instrument_row()

        def save_song(e):

            if title_field.value == "":
                message.value = "曲名を入力してください！"
                message.color = ft.Colors.RED
                page.update()
                return

            instruments_data = []

            for name_field, divisions_field in instrument_rows:

                if (
                    name_field.value == ""
                    or divisions_field.value == ""
                ):
                    continue

                divisions = []
                capacities = []

                try:
                    for pair in divisions_field.value.split(","):
                        div, cap = pair.split(":")
                        divisions.append(div.strip())
                        capacities.append(int(cap.strip()))
                except ValueError:
                    message.value = (
                        f"{name_field.value} の分割の書き方が"
                        "正しくありません"
                        "（例: 1st:3,2nd:3,Picc:1）"
                    )
                    message.color = ft.Colors.RED
                    page.update()
                    return

                instruments_data.append(
                    (name_field.value, divisions, capacities)
                )

            if not instruments_data:
                message.value = "楽器を1つ以上入力してください！"
                message.color = ft.Colors.RED
                page.update()
                return

            conn = sqlite3.connect("bandmatch.db")

            max_order = conn.execute(
                """
                SELECT COALESCE(MAX(sort_order), -1)
                FROM songs
                WHERE event_part_id=?
                """,
                (event_part_id,),
            ).fetchone()[0]

            cur = conn.execute(
                """
                INSERT INTO songs
                (event_part_id, title, sort_order)
                VALUES (?, ?, ?)
                """,
                (event_part_id, title_field.value, max_order + 1),
            )

            song_id = cur.lastrowid

            for name, divisions, capacities in instruments_data:

                conn.execute(
                    """
                    INSERT INTO song_instruments
                    (
                        song_id,
                        instrument_name,
                        divisions,
                        capacity_per_division
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        song_id,
                        name,
                        json.dumps(divisions, ensure_ascii=False),
                        json.dumps(capacities),
                    ),
                )

            conn.commit()
            conn.close()

            add_song_dialog.open = False
            page.update()

            show_event_detail(event_type)

        def cancel(e):
            add_song_dialog.open = False
            page.update()

        add_song_dialog = ft.AlertDialog(
            title=ft.Text(
                "🎵 曲を追加",
                size=20,
                weight=ft.FontWeight.BOLD,
            ),
            content=ft.Column(
                controls=[
                    title_field,
                    ft.Text(
                        "パート編成（楽器ごとに分割と定員を指定）",
                        size=13,
                        weight=ft.FontWeight.BOLD,
                    ),
                    instrument_column,
                    ft.TextButton(
                        "＋ 楽器を追加",
                        on_click=add_instrument_row,
                    ),
                    message,
                ],
                tight=True,
                width=380,
                height=420,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton("追加する", on_click=save_song),
                ft.TextButton("キャンセル", on_click=cancel),
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER,
        )

        page.show_dialog(add_song_dialog)

    # ==========================================
    # ★追加：曲の詳細画面
    # ==========================================

    def show_song_detail(song_id, event_type):

        page.clean()

        conn = sqlite3.connect("bandmatch.db")

        song = conn.execute(
            "SELECT title FROM songs WHERE id=?",
            (song_id,),
        ).fetchone()

        instruments = conn.execute(
            """
            SELECT instrument_name, divisions, capacity_per_division
            FROM song_instruments
            WHERE song_id=?
            """,
            (song_id,),
        ).fetchall()

        conn.close()

        title = ft.Text(
            f"🎵 {song[0]}",
            size=26,
            weight=ft.FontWeight.BOLD,
        )

        part_controls = [
            ft.Text("パート編成", size=18, weight=ft.FontWeight.BOLD)
        ]

        for name, div_json, cap_json in instruments:

            divisions = json.loads(div_json)
            capacities = json.loads(cap_json)

            detail = " / ".join(
                f"{d}（定員{c}）"
                for d, c in zip(divisions, capacities)
            )

            part_controls.append(
                ft.Text(f"・{name}：{detail}", size=15)
            )

        result_button = ft.OutlinedButton(
            "📊 決定結果を見る",
            width=350,
            height=50,
            on_click=(
                lambda e: show_part_results(song_id, event_type)
            ),
        )

        back_button = ft.OutlinedButton(
            "戻る",
            width=350,
            height=50,
            on_click=lambda e: show_event_detail(event_type),
        )

        action_buttons = []

        if is_admin:

            action_buttons.append(
                ft.ElevatedButton(
                    "⚙ パート決め（管理者）",
                    width=350,
                    height=50,
                    on_click=(
                        lambda e: show_part_admin(song_id, event_type)
                    ),
                )
            )

        else:

            action_buttons.append(
                ft.ElevatedButton(
                    "🗳 パート希望を出す",
                    width=350,
                    height=50,
                    on_click=(
                        lambda e: show_part_survey(song_id, event_type)
                    ),
                )
            )

        page.add(
            ft.Column(
                controls=[
                    title,
                    *part_controls,
                    ft.Divider(),
                    *action_buttons,
                    result_button,
                    back_button,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=15,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    # ==========================================
    # ★追加：パート希望調査（ユーザー）
    # ==========================================

    def show_part_survey(song_id, event_type):

        page.clean()

        conn = sqlite3.connect("bandmatch.db")

        song = conn.execute(
            "SELECT title FROM songs WHERE id=?",
            (song_id,),
        ).fetchone()

        instruments = conn.execute(
            """
            SELECT instrument_name, divisions
            FROM song_instruments
            WHERE song_id=?
            """,
            (song_id,),
        ).fetchall()

        existing = conn.execute(
            """
            SELECT rank, instrument_name, division
            FROM part_preferences
            WHERE song_id=? AND user_id=?
            ORDER BY rank
            """,
            (song_id, current_user_id),
        ).fetchall()

        conn.close()

        options = []

        for name, div_json in instruments:
            for d in json.loads(div_json):
                options.append(
                    ft.dropdown.Option(
                        key=f"{name}|{d}",
                        text=f"{name}　{d}",
                    )
                )

        options.append(ft.dropdown.Option(key="|降り", text="降り"))

        existing_map = {
            rank: f"{inst}|{div}" for rank, inst, div in existing
        }

        dropdowns = []

        for rank in range(1, 5):

            dd = ft.Dropdown(
                label=f"第{rank}希望",
                width=350,
                options=options,
                value=existing_map.get(rank),
            )

            dropdowns.append(dd)

        message = ft.Text("", size=14)

        def submit(e):

            values = [dd.value for dd in dropdowns]

            if any(v is None for v in values):
                message.value = "すべての希望を選択してください！"
                message.color = ft.Colors.RED
                page.update()
                return

            if len(set(values)) != len(values):
                message.value = (
                    "同じ組み合わせを複数選ぶことはできません！"
                )
                message.color = ft.Colors.RED
                page.update()
                return

            conn = sqlite3.connect("bandmatch.db")

            conn.execute(
                """
                DELETE FROM part_preferences
                WHERE song_id=? AND user_id=?
                """,
                (song_id, current_user_id),
            )

            for rank, value in enumerate(values, start=1):

                instrument, division = value.split("|")

                conn.execute(
                    """
                    INSERT INTO part_preferences
                    (song_id, user_id, rank, instrument_name, division)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        song_id,
                        current_user_id,
                        rank,
                        instrument,
                        division,
                    ),
                )

            conn.commit()
            conn.close()

            message.value = "希望を保存しました！🎺"
            message.color = ft.Colors.GREEN
            page.update()

        back_button = ft.OutlinedButton(
            "戻る",
            width=350,
            height=50,
            on_click=lambda e: show_song_detail(song_id, event_type),
        )

        page.add(
            ft.Column(
                controls=[
                    ft.Text(
                        f"🗳 {song[0]} のパート希望",
                        size=24,
                        weight=ft.FontWeight.BOLD,
                    ),
                    *dropdowns,
                    message,
                    ft.ElevatedButton(
                        "保存する",
                        width=350,
                        height=50,
                        on_click=submit,
                    ),
                    back_button,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=15,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    # ==========================================
    # ★追加：出席率を計算
    # ==========================================

    def calculate_attendance_rate(conn, user_id):

        total = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE user_id=?",
            (user_id,),
        ).fetchone()[0]

        if total == 0:
            return 0.0

        attended = conn.execute(
            """
            SELECT COUNT(*) FROM attendance
            WHERE user_id=? AND status IN ('出席','遅刻','早退')
            """,
            (user_id,),
        ).fetchone()[0]

        return attended / total

    # ==========================================
    # ★追加：合宿の出欠を取得
    # 未設定の場合は「来ない」扱い（安全側）
    # ==========================================

    def get_camp_attendance(conn, camp_type, user_id):

        row = conn.execute(
            """
            SELECT attending FROM camp_attendance
            WHERE camp_type=? AND user_id=?
            """,
            (camp_type, user_id),
        ).fetchone()

        return bool(row[0]) if row else False

    # ==========================================
    # ★追加：自動割り振りアルゴリズム
    #
    # スコア = 出席率×3 + 希望度×2 + 学年重み×1
    # （出席率＞希望度＞学年 の優先度を反映）
    #
    # 1) スコアの高い順に、第1〜第4希望のうち
    #    空きがある一番良い希望へ割り当てる
    # 2) 定員から溢れた人は「降り」
    # 3) 合宿に1人も来ない人しかいないパートができた場合、
    #    そのパートを希望していた合宿参加者と
    #    スコアが一番低いメンバーを入れ替える（できる範囲で）
    #
    # ※ヒューリスティックな実装のため、完全な最適解では
    # 　ないケースがあります。結果は「確定」を押すまで
    # 　保存されないので、必要に応じて希望を調整してから
    # 　再実行してください。
    # ==========================================

    def auto_assign_song(song_id, event_type):

        conn = sqlite3.connect("bandmatch.db")

        instruments = conn.execute(
            """
            SELECT instrument_name, divisions, capacity_per_division
            FROM song_instruments
            WHERE song_id=?
            """,
            (song_id,),
        ).fetchall()

        capacity_map = {}

        for name, div_json, cap_json in instruments:
            divs = json.loads(div_json)
            caps = json.loads(cap_json)
            for d, c in zip(divs, caps):
                capacity_map[(name, d)] = c

        prefs = conn.execute(
            """
            SELECT
                part_preferences.user_id,
                part_preferences.rank,
                part_preferences.instrument_name,
                part_preferences.division,
                users.grade
            FROM part_preferences
            JOIN users ON users.id = part_preferences.user_id
            WHERE part_preferences.song_id=?
            ORDER BY part_preferences.user_id, part_preferences.rank
            """,
            (song_id,),
        ).fetchall()

        camp_type = EVENT_TYPE_CAMP[event_type]

        user_prefs = {}
        user_grade = {}

        for user_id, rank, instrument, division, grade in prefs:
            user_prefs.setdefault(user_id, []).append(
                (rank, instrument, division)
            )
            user_grade[user_id] = grade

        candidates = []

        for user_id, choices in user_prefs.items():

            attendance_rate = calculate_attendance_rate(
                conn, user_id
            )
            grade = user_grade.get(user_id, "")
            grade_weight = GRADE_WEIGHT.get(grade, 0)
            camp_ok = get_camp_attendance(
                conn, camp_type, user_id
            )

            for rank, instrument, division in choices:

                if division == "降り":
                    continue

                pref_score = max(5 - rank, 0)

                score = (
                    attendance_rate * 3
                    + pref_score * 2
                    + grade_weight * 1
                )

                candidates.append(
                    {
                        "user_id": user_id,
                        "instrument": instrument,
                        "division": division,
                        "rank": rank,
                        "score": score,
                        "camp_ok": camp_ok,
                    }
                )

        candidates.sort(key=lambda c: c["score"], reverse=True)

        assigned = {}
        slot_members = {}
        remaining_capacity = dict(capacity_map)

        for c in candidates:

            uid = c["user_id"]

            if uid in assigned:
                continue

            key = (c["instrument"], c["division"])
            cap = remaining_capacity.get(key, 0)

            if cap > 0:
                assigned[uid] = key
                slot_members.setdefault(key, []).append(uid)
                remaining_capacity[key] = cap - 1

        for uid in user_prefs:
            if uid not in assigned:
                assigned[uid] = ("", "降り")
                slot_members.setdefault(("", "降り"), []).append(uid)

        # ---- 合宿カバレッジ修正パス ----

        for key, members in list(slot_members.items()):

            instrument, division = key

            if division == "降り" or not members:
                continue

            if any(
                get_camp_attendance(conn, camp_type, m)
                for m in members
            ):
                continue

            swap_candidates = [
                c
                for c in candidates
                if c["instrument"] == instrument
                and c["division"] == division
                and c["camp_ok"]
                and assigned.get(c["user_id"]) != key
            ]

            swap_candidates.sort(
                key=lambda c: c["score"], reverse=True
            )

            if not swap_candidates:
                # 合宿に来る候補が誰もいない場合は
                # 手動での調整が必要（そのまま残す）
                continue

            newcomer = swap_candidates[0]
            uid_new = newcomer["user_id"]
            old_key = assigned[uid_new]

            current_scores = [
                c for c in candidates if c["user_id"] in members
            ]
            current_scores.sort(key=lambda c: c["score"])

            if not current_scores:
                continue

            uid_out = current_scores[0]["user_id"]

            slot_members[key].remove(uid_out)
            slot_members[key].append(uid_new)

            slot_members.setdefault(old_key, [])
            if uid_new in slot_members[old_key]:
                slot_members[old_key].remove(uid_new)
            slot_members[old_key].append(uid_out)

            assigned[uid_new] = key
            assigned[uid_out] = old_key

        conn.close()

        return assigned

    # ==========================================
    # ★追加：割り振り結果を確定保存
    # ==========================================

    def commit_assignments(song_id, assigned):

        conn = sqlite3.connect("bandmatch.db")

        for user_id, (instrument, division) in assigned.items():

            existing = conn.execute(
                """
                SELECT id FROM part_assignments
                WHERE song_id=? AND user_id=?
                """,
                (song_id, user_id),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE part_assignments
                    SET instrument_name=?, division=?
                    WHERE song_id=? AND user_id=?
                    """,
                    (instrument, division, song_id, user_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO part_assignments
                    (song_id, user_id, instrument_name, division)
                    VALUES (?, ?, ?, ?)
                    """,
                    (song_id, user_id, instrument, division),
                )

        conn.commit()
        conn.close()

    # ==========================================
    # ★追加：パート決め画面（管理者）
    # 希望確認 → 自動決定 → 結果確定
    # ==========================================

    def show_part_admin(song_id, event_type):

        if not is_admin:
            show_home()
            return

        page.clean()

        conn = sqlite3.connect("bandmatch.db")

        song = conn.execute(
            "SELECT title FROM songs WHERE id=?",
            (song_id,),
        ).fetchone()

        prefs = conn.execute(
            """
            SELECT
                users.nickname,
                users.email,
                part_preferences.rank,
                part_preferences.instrument_name,
                part_preferences.division
            FROM part_preferences
            JOIN users ON users.id = part_preferences.user_id
            WHERE part_preferences.song_id=?
            ORDER BY users.id, part_preferences.rank
            """,
            (song_id,),
        ).fetchall()

        conn.close()

        pref_controls = [
            ft.Text("📋 希望確認", size=18, weight=ft.FontWeight.BOLD)
        ]

        grouped = {}

        for nickname, email, rank, instrument, division in prefs:
            name = nickname if nickname else email
            grouped.setdefault(name, []).append(
                (rank, instrument, division)
            )

        if not grouped:
            pref_controls.append(
                ft.Text("まだ希望が提出されていません", size=14)
            )

        for name, choices in grouped.items():

            choice_text = " / ".join(
                f"第{r}希望:{i} {d}" for r, i, d in sorted(choices)
            )

            pref_controls.append(
                ft.Text(f"・{name}：{choice_text}", size=13)
            )

        preview_column = ft.Column(spacing=5)
        message = ft.Text("", size=14)

        computed_assignment = {"data": None}

        def run_auto_assign(e):

            assigned = auto_assign_song(song_id, event_type)
            computed_assignment["data"] = assigned

            conn = sqlite3.connect("bandmatch.db")

            preview_column.controls.clear()

            preview_column.controls.append(
                ft.Text(
                    "🤖 自動決定（プレビュー・まだ確定していません）",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                )
            )

            by_slot = {}
            for uid, (instrument, division) in assigned.items():
                by_slot.setdefault((instrument, division), []).append(uid)

            for (instrument, division), uids in by_slot.items():

                names = []
                for uid in uids:
                    row = conn.execute(
                        "SELECT nickname, email FROM users WHERE id=?",
                        (uid,),
                    ).fetchone()
                    names.append(row[0] if row[0] else row[1])

                label = (
                    "降り"
                    if division == "降り"
                    else f"{instrument} {division}"
                )

                preview_column.controls.append(
                    ft.Text(f"【{label}】{', '.join(names)}", size=14)
                )

            conn.close()

            message.value = (
                "自動決定を計算しました。内容を確認して"
                "「結果を確定する」を押してください。"
            )
            message.color = ft.Colors.BLUE
            page.update()

        def confirm_result(e):

            if computed_assignment["data"] is None:
                message.value = (
                    "先に「🤖 自動決定を実行」を押してください！"
                )
                message.color = ft.Colors.RED
                page.update()
                return

            commit_assignments(song_id, computed_assignment["data"])

            message.value = "パートを確定しました！🎺"
            message.color = ft.Colors.GREEN
            page.update()

        back_button = ft.OutlinedButton(
            "戻る",
            width=350,
            height=50,
            on_click=lambda e: show_song_detail(song_id, event_type),
        )

        page.add(
            ft.Column(
                controls=[
                    ft.Text(
                        f"⚙ {song[0]} のパート決め（管理者）",
                        size=22,
                        weight=ft.FontWeight.BOLD,
                    ),
                    *pref_controls,
                    ft.Divider(),
                    ft.ElevatedButton(
                        "🤖 自動決定を実行",
                        width=350,
                        height=50,
                        on_click=run_auto_assign,
                    ),
                    preview_column,
                    ft.ElevatedButton(
                        "✅ 結果を確定する",
                        width=350,
                        height=50,
                        on_click=confirm_result,
                    ),
                    message,
                    back_button,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=15,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    # ==========================================
    # ★追加：パート決定結果（ユーザー・管理者共通）
    # ==========================================

    def show_part_results(song_id, event_type):

        page.clean()

        conn = sqlite3.connect("bandmatch.db")

        song = conn.execute(
            "SELECT title FROM songs WHERE id=?",
            (song_id,),
        ).fetchone()

        results = conn.execute(
            """
            SELECT
                users.nickname,
                users.email,
                part_assignments.instrument_name,
                part_assignments.division
            FROM part_assignments
            JOIN users ON users.id = part_assignments.user_id
            WHERE part_assignments.song_id=?
            """,
            (song_id,),
        ).fetchall()

        conn.close()

        result_controls = []

        if not results:
            result_controls.append(
                ft.Text(
                    "まだパートが確定していません",
                    size=16,
                    color=ft.Colors.GREY,
                )
            )
        else:

            grouped = {}

            for nickname, email, instrument, division in results:
                name = nickname if nickname else email
                label = (
                    "降り"
                    if division == "降り"
                    else f"{instrument} {division}"
                )
                grouped.setdefault(label, []).append(name)

            for label, names in grouped.items():
                result_controls.append(
                    ft.Text(f"【{label}】{', '.join(names)}", size=15)
                )

        back_button = ft.OutlinedButton(
            "戻る",
            width=350,
            height=50,
            on_click=lambda e: show_song_detail(song_id, event_type),
        )

        page.add(
            ft.Column(
                controls=[
                    ft.Text(
                        f"📊 {song[0]} のパート決定結果",
                        size=22,
                        weight=ft.FontWeight.BOLD,
                    ),
                    *result_controls,
                    back_button,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=15,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    # ==========================================
    # ホーム画面
    # ==========================================

    def show_home():

        page.clean()

        def get_practices():

            conn = sqlite3.connect("bandmatch.db")

            rows = conn.execute(
                """
                SELECT
                    id,
                    date,
                    start_time,
                    end_time,
                    location,
                    content
                FROM practices
                ORDER BY date
                """
            ).fetchall()

            conn.close()

            return rows

        def get_attendance_counts(practice_id):

            conn = sqlite3.connect("bandmatch.db")

            rows = conn.execute(
                """
                SELECT status, COUNT(*)
                FROM attendance
                WHERE practice_id = ?
                GROUP BY status
                """,
                (practice_id,),
            ).fetchall()

            total_users = conn.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0]

            conn.close()

            counts = {
                "出席": 0,
                "欠席": 0,
                "遅刻": 0,
                "早退": 0,
            }

            for status, count in rows:
                if status in counts:
                    counts[status] = count

            answered = sum(counts.values())

            counts["未回答"] = max(
                total_users - answered,
                0,
            )

            return counts

        def build_summary_text(counts):

            return (
                f"出席 {counts['出席']}人 / "
                f"欠席 {counts['欠席']}人 / "
                f"遅刻 {counts['遅刻']}人 / "
                f"早退 {counts['早退']}人 / "
                f"未回答 {counts['未回答']}人"
            )

        def get_attendance_list(practice_id):

            conn = sqlite3.connect("bandmatch.db")

            rows = conn.execute(
                """
                SELECT
                    users.nickname,
                    users.email,
                    attendance.status
                FROM attendance
                JOIN users
                ON attendance.user_id = users.id
                WHERE attendance.practice_id = ?
                ORDER BY attendance.status
                """,
                (practice_id,),
            ).fetchall()

            conn.close()

            display_rows = []

            for nickname, email, status in rows:

                display_name = nickname if nickname else email

                display_rows.append((display_name, status))

            return display_rows

        def show_practice_detail(practice):

            practice_id = practice[0]
            practice_date = practice[1]
            start_time = practice[2]
            end_time = practice[3]
            location = practice[4]
            content = practice[5]

            conn = sqlite3.connect("bandmatch.db")

            attendance = conn.execute(
                """
                SELECT status
                FROM attendance
                WHERE practice_id = ?
                AND user_id = ?
                """,
                (
                    practice_id,
                    current_user_id,
                ),
            ).fetchone()

            conn.close()

            if attendance:
                current_status = (
                    f"現在の出欠：{attendance[0]}"
                )
            else:
                current_status = "現在の出欠：未回答"

            attendance_message = ft.Text(
                current_status,
                size=15,
            )

            summary_counts = get_attendance_counts(
                practice_id
            )

            summary_message = ft.Text(
                build_summary_text(summary_counts),
                size=14,
            )

            def close_dialog(e):
                detail_dialog.open = False
                page.update()

            def show_attendees_list(e):

                attendee_rows = get_attendance_list(
                    practice_id
                )

                if attendee_rows:

                    list_controls = [
                        ft.Text(
                            f"{status}：{display_name}",
                            size=14,
                        )
                        for display_name, status in attendee_rows
                    ]

                else:

                    list_controls = [
                        ft.Text(
                            "まだ出欠登録がありません",
                            size=14,
                        )
                    ]

                def close_attendees_dialog(e):
                    attendees_dialog.open = False
                    page.update()

                attendees_dialog = ft.AlertDialog(
                    title=ft.Text(
                        "👥 出席者一覧",
                        size=20,
                        weight=ft.FontWeight.BOLD,
                    ),

                    content=ft.Column(
                        controls=list_controls,
                        tight=True,
                        width=300,
                        height=300,
                        scroll=ft.ScrollMode.AUTO,
                    ),

                    actions=[
                        ft.TextButton(
                            "閉じる",
                            on_click=close_attendees_dialog,
                        ),
                    ],

                    actions_alignment=(
                        ft.MainAxisAlignment.CENTER
                    ),
                )

                page.show_dialog(attendees_dialog)

            def save_status(status):

                conn = sqlite3.connect("bandmatch.db")

                existing = conn.execute(
                    """
                    SELECT id
                    FROM attendance
                    WHERE practice_id = ?
                    AND user_id = ?
                    """,
                    (
                        practice_id,
                        current_user_id,
                    ),
                ).fetchone()

                if existing:

                    conn.execute(
                        """
                        UPDATE attendance
                        SET status = ?
                        WHERE practice_id = ?
                        AND user_id = ?
                        """,
                        (
                            status,
                            practice_id,
                            current_user_id,
                        ),
                    )

                else:

                    conn.execute(
                        """
                        INSERT INTO attendance
                        (
                            practice_id,
                            user_id,
                            status
                        )
                        VALUES (?, ?, ?)
                        """,
                        (
                            practice_id,
                            current_user_id,
                            status,
                        ),
                    )

                conn.commit()
                conn.close()

                attendance_message.value = (
                    f"出欠を「{status}」にしました！"
                )

                attendance_message.color = ft.Colors.GREEN

                new_counts = get_attendance_counts(
                    practice_id
                )

                summary_message.value = (
                    build_summary_text(new_counts)
                )

                detail_dialog.open = False

                page.update()

            detail_dialog = ft.AlertDialog(
                title=ft.Text(
                    "🎵 練習詳細",
                    size=22,
                    weight=ft.FontWeight.BOLD,
                ),

                content=ft.Column(
                    controls=[
                        ft.Text(
                            f"📅 {practice_date}",
                            size=17,
                        ),

                        ft.Text(
                            f"⏰ {start_time} ～ {end_time}",
                            size=17,
                        ),

                        ft.Text(
                            f"📍 {location}",
                            size=17,
                        ),

                        ft.Divider(),

                        ft.Text(
                            "練習内容",
                            size=17,
                            weight=ft.FontWeight.BOLD,
                        ),

                        ft.Text(
                            content
                            if content
                            else "（登録なし）",
                            size=16,
                        ),

                        ft.Divider(),

                        ft.Text(
                            "👤 あなたの出欠",
                            size=17,
                            weight=ft.FontWeight.BOLD,
                        ),

                        attendance_message,

                        ft.Divider(),

                        ft.Text(
                            "👥 出席状況",
                            size=17,
                            weight=ft.FontWeight.BOLD,
                        ),

                        summary_message,

                        ft.OutlinedButton(
                            "出席者を見る",
                            on_click=show_attendees_list,
                        ),
                    ],
                    tight=True,
                    width=320,
                    scroll=ft.ScrollMode.AUTO,
                ),

                actions=[
                    ft.TextButton(
                        content="🟢 出席",
                        on_click=lambda e: save_status("出席"),
                    ),

                    ft.TextButton(
                        content="🔴 欠席",
                        on_click=lambda e: save_status("欠席"),
                    ),

                    ft.TextButton(
                        content="🟡 遅刻",
                        on_click=lambda e: save_status("遅刻"),
                    ),

                    ft.TextButton(
                        content="🔵 早退",
                        on_click=lambda e: save_status("早退"),
                    ),

                    ft.TextButton(
                        content="閉じる",
                        on_click=close_dialog,
                    ),
                ],

                actions_alignment=ft.MainAxisAlignment.CENTER,
            )

            page.show_dialog(detail_dialog)

        def create_calendar(year, month):

            practices = get_practices()

            practice_dict = {}

            for practice in practices:

                practice_date = practice[1]

                if practice_date not in practice_dict:
                    practice_dict[practice_date] = []

                practice_dict[practice_date].append(practice)

            cal = calendar.Calendar(firstweekday=0)

            calendar_rows = []

            calendar_rows.append(
                ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Text(
                                "月",
                                text_align=ft.TextAlign.CENTER,
                            ),
                            width=45,
                        ),

                        ft.Container(
                            content=ft.Text(
                                "火",
                                text_align=ft.TextAlign.CENTER,
                            ),
                            width=45,
                        ),

                        ft.Container(
                            content=ft.Text(
                                "水",
                                text_align=ft.TextAlign.CENTER,
                            ),
                            width=45,
                        ),

                        ft.Container(
                            content=ft.Text(
                                "木",
                                text_align=ft.TextAlign.CENTER,
                            ),
                            width=45,
                        ),

                        ft.Container(
                            content=ft.Text(
                                "金",
                                text_align=ft.TextAlign.CENTER,
                            ),
                            width=45,
                        ),

                        ft.Container(
                            content=ft.Text(
                                "土",
                                text_align=ft.TextAlign.CENTER,
                                color=ft.Colors.BLUE,
                            ),
                            width=45,
                        ),

                        ft.Container(
                            content=ft.Text(
                                "日",
                                text_align=ft.TextAlign.CENTER,
                                color=ft.Colors.RED,
                            ),
                            width=45,
                        ),
                    ],

                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=0,
                )
            )

            for week in cal.monthdayscalendar(year, month):

                week_controls = []

                for day in week:

                    if day == 0:

                        week_controls.append(
                            ft.Container(
                                width=45,
                                height=65,
                            )
                        )

                        continue

                    date_string = (
                        f"{year:04d}/"
                        f"{month:02d}/"
                        f"{day:02d}"
                    )

                    day_controls = [
                        ft.Text(
                            str(day),
                            size=16,
                            weight=ft.FontWeight.BOLD,
                            text_align=ft.TextAlign.CENTER,
                        )
                    ]

                    if date_string in practice_dict:

                        for practice in practice_dict[date_string]:

                            music_button = ft.TextButton(
                                content=ft.Text(
                                    "🎵",
                                    size=18,
                                ),
                                on_click=lambda e, p=practice:
                                    show_practice_detail(p),
                            )

                            day_controls.append(
                                music_button
                            )

                    week_controls.append(
                        ft.Container(
                            content=ft.Column(
                                controls=day_controls,
                                horizontal_alignment=(
                                    ft.CrossAxisAlignment.CENTER
                                ),
                                spacing=0,
                            ),

                            width=45,
                            height=65,

                            alignment=(
                                ft.Alignment(0, 0)
                            ),
                        )
                    )

                calendar_rows.append(
                    ft.Row(
                        controls=week_controls,
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=0,
                    )
                )

            return ft.Column(
                controls=calendar_rows,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=3,
            )

        today = datetime.date.today()

        current_year = today.year
        current_month = today.month

        year_dropdown = ft.Dropdown(
            label="年",
            value=str(current_year),
            options=[
                ft.dropdown.Option(str(year))
                for year in range(
                    current_year - 5,
                    current_year + 6
                )
            ],
            width=120,
        )

        month_dropdown = ft.Dropdown(
            label="月",
            value=str(current_month),
            options=[
                ft.dropdown.Option(str(month))
                for month in range(1, 13)
            ],
            width=100,
        )

        def update_calendar():

            calendar_title.value = (
                f"{current_year}年{current_month}月"
            )

            calendar_container.content = create_calendar(
                current_year,
                current_month,
            )

            year_dropdown.value = str(current_year)
            month_dropdown.value = str(current_month)

            page.update()

        def year_changed(e):

            nonlocal current_year

            if e.control.value:
                current_year = int(e.control.value)

            update_calendar()

        def month_changed(e):

            nonlocal current_month

            if e.control.value:
                current_month = int(e.control.value)

            update_calendar()

        year_dropdown.on_select = year_changed
        month_dropdown.on_select = month_changed

        def previous_month(e):

            nonlocal current_year
            nonlocal current_month

            current_month -= 1

            if current_month == 0:
                current_month = 12
                current_year -= 1

            update_calendar()

        def next_month(e):

            nonlocal current_year
            nonlocal current_month

            current_month += 1

            if current_month == 13:
                current_month = 1
                current_year += 1

            update_calendar()

        calendar_title = ft.Text(
            f"{current_year}年{current_month}月",
            size=22,
            weight=ft.FontWeight.BOLD,
        )

        previous_button = ft.ElevatedButton(
            "← 前月",
            on_click=previous_month,
        )

        next_button = ft.ElevatedButton(
            "翌月 →",
            on_click=next_month,
        )

        date_selection = ft.Row(
            controls=[
                year_dropdown,
                month_dropdown,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10,
        )

        calendar_container = ft.Container(
            content=create_calendar(
                current_year,
                current_month,
            ),

            padding=10,

            border=ft.Border.all(
                1,
                "#CCCCCC",
            ),

            border_radius=10,

            bgcolor="#FFFFFF",
        )

        home_title = ft.Text(
            "🎺 BandMatch",
            size=32,
            weight=ft.FontWeight.BOLD,
        )

        home_text = ft.Text(
            "ホーム",
            size=24,
        )

        role_label = "管理者" if is_admin else "部員"

        login_message = ft.Text(
            f"ようこそ、{current_user_name} さん！（{role_label}）",
            size=16,
            color=ft.Colors.GREEN,
        )

        # ★追加：イベント（セトリ・パート希望調査/決定結果の入口）
        events_button = ft.ElevatedButton(
            "🎪 イベント",
            width=350,
            height=50,
            on_click=lambda e: show_events(),
        )

        # ★変更：管理者/部員で表示するボタンを分ける
        role_buttons = []

        if is_admin:

            role_buttons.append(
                ft.ElevatedButton(
                    "🎺 練習日を登録",
                    width=350,
                    height=50,
                    on_click=lambda e: show_admin(),
                )
            )

            role_buttons.append(
                ft.OutlinedButton(
                    "🏕 合宿に誰が来るか（管理者）",
                    width=350,
                    height=50,
                    on_click=lambda e: show_camp_admin_view(),
                )
            )

            role_buttons.append(
                ft.OutlinedButton(
                    "⚙ 管理者管理",
                    width=350,
                    height=50,
                    on_click=lambda e: show_admin_management(),
                )
            )

        else:

            role_buttons.append(
                ft.OutlinedButton(
                    "🏕 合宿の出欠設定",
                    width=350,
                    height=50,
                    on_click=lambda e: show_camp_survey(),
                )
            )

        logout_button = ft.OutlinedButton(
            "ログアウト",
            width=350,
            height=50,
            on_click=lambda e: show_login(),
        )

        page.add(
            ft.Column(
                controls=[

                    home_title,

                    home_text,

                    login_message,

                    events_button,

                    *role_buttons,

                    ft.Divider(),

                    ft.Text(
                        "📅 練習カレンダー",
                        size=24,
                        weight=ft.FontWeight.BOLD,
                    ),

                    date_selection,

                    ft.Row(
                        controls=[
                            previous_button,
                            calendar_title,
                            next_button,
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=15,
                    ),

                    calendar_container,

                    logout_button,
                ],

                horizontal_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),

                spacing=15,
            )
        )

    # ==========================================
    # 最初はログイン画面
    # ==========================================

    show_login()


# ==========================================
# アプリ起動
# ==========================================

if __name__ == "__main__":
    ft.run(main, assets_dir="assets")