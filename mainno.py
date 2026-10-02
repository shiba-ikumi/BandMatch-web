import flet as ft
import sqlite3
import datetime
import calendar


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
    # grade： 08=1年生 / 07=2年生 / 06=3年生 / 05=4年生
    # ------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grade TEXT,
            name TEXT,
            nickname TEXT,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    """)

    # ------------------------------------------
    # ★追加：既存のusersテーブルに
    # grade / name / nickname が無い場合は追加する
    # （前のバージョンで作られたbandmatch.dbでも
    # 　壊れずに使えるようにするため）
    # ------------------------------------------

    for column_name, column_type in [
        ("grade", "TEXT"),
        ("name", "TEXT"),
        ("nickname", "TEXT"),
    ]:

        try:
            conn.execute(
                f"ALTER TABLE users ADD COLUMN "
                f"{column_name} {column_type}"
            )
        except sqlite3.OperationalError:
            # すでにカラムがある場合はここに来る
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

    # ==========================================
    # 現在ログインしているユーザー
    # ==========================================

    # 今はテスト用として1番のユーザーを使用
    # 後で本当のログインユーザーIDに変更する
    current_user_id = 1

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

        # --------------------------------------
        # ログイン処理
        # --------------------------------------

        def login_click(e):

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

            # テスト用ログイン
            elif (
                email.value == "test@example.com"
                and password.value == "1234"
            ):
                show_home()
                return

            else:
                message.value = (
                    "メールアドレスまたはパスワードが違います"
                )
                message.color = ft.Colors.RED

            page.update()

        # --------------------------------------
        # ログインボタン
        # --------------------------------------

        login_button = ft.ElevatedButton(
            "ログイン",
            width=350,
            height=50,
            on_click=login_click,
        )

        # --------------------------------------
        # 新規登録ボタン
        # --------------------------------------

        signup_button = ft.OutlinedButton(
            "新規登録",
            width=350,
            height=50,
            on_click=show_signup,
        )

        # --------------------------------------
        # 画面表示
        # --------------------------------------

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

        # --------------------------------------
        # ★追加：学年（1〜4年生表記／内部は08〜05）
        # --------------------------------------

        grade_dropdown = ft.Dropdown(
            label="学年",
            width=350,
            options=[
                ft.dropdown.Option(
                    key=code,
                    text=code,
                )
                for code in ["08", "07", "06", "05"]
            ],
        )

        # --------------------------------------
        # ★追加：氏名
        # --------------------------------------

        name_field = ft.TextField(
            label="氏名",
            hint_text="山田 太郎",
            width=350,
        )

        # --------------------------------------
        # ★追加：あだ名
        # --------------------------------------

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

        # --------------------------------------
        # アカウント作成
        # --------------------------------------

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

        # --------------------------------------
        # 作成ボタン
        # --------------------------------------

        create_button = ft.ElevatedButton(
            "アカウント作成",
            width=350,
            height=50,
            on_click=create_account,
        )

        # --------------------------------------
        # 戻るボタン
        # --------------------------------------

        back_button = ft.OutlinedButton(
            "ログインに戻る",
            width=350,
            height=50,
            on_click=lambda e: show_login(),
        )

        # --------------------------------------
        # 画面表示
        # --------------------------------------

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
    # 管理者画面
    # ==========================================

    def show_admin():

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

        # --------------------------------------
        # 練習日
        # --------------------------------------

        date_field = ft.TextField(
            label="練習日",
            hint_text="2026/08/20",
            width=350,
        )

        # --------------------------------------
        # 開始時間
        # --------------------------------------

        start_time_field = ft.TextField(
            label="開始時間",
            hint_text="18:00",
            width=350,
        )

        # --------------------------------------
        # 終了時間
        # --------------------------------------

        end_time_field = ft.TextField(
            label="終了時間",
            hint_text="21:00",
            width=350,
        )

        # --------------------------------------
        # 場所
        # --------------------------------------

        location_field = ft.TextField(
            label="場所",
            hint_text="○○音楽室",
            width=350,
        )

        # --------------------------------------
        # 練習内容
        # --------------------------------------

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

        # ======================================
        # 練習日登録
        # ======================================

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

        # --------------------------------------
        # 登録ボタン
        # --------------------------------------

        register_button = ft.ElevatedButton(
            "練習日を登録",
            width=350,
            height=50,
            on_click=register_practice,
        )

        # --------------------------------------
        # ホームに戻る
        # --------------------------------------

        back_button = ft.OutlinedButton(
            "ホームに戻る",
            width=350,
            height=50,
            on_click=lambda e: show_home(),
        )

        # --------------------------------------
        # 画面表示
        # --------------------------------------

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
    # ホーム画面
    # ==========================================

    def show_home():

        page.clean()

        # ======================================
        # 練習データ取得
        # ======================================

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

        # ======================================
        # 出欠の集計（人数）を取得
        # ======================================

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

            # 未回答 = 全メンバー数 - 回答済み人数
            counts["未回答"] = max(
                total_users - answered,
                0,
            )

            return counts

        # ======================================
        # 出欠集計のテキストを作る
        # ======================================

        def build_summary_text(counts):

            return (
                f"出席 {counts['出席']}人 / "
                f"欠席 {counts['欠席']}人 / "
                f"遅刻 {counts['遅刻']}人 / "
                f"早退 {counts['早退']}人 / "
                f"未回答 {counts['未回答']}人"
            )

        # ======================================
        # ★変更：出欠者一覧を
        # 「あだ名」で取得するようにした
        # （あだ名が未登録の人はメールアドレスで表示）
        # ======================================

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

        # ======================================
        # 出欠状況を保存
        # ======================================

        def save_attendance(
            practice_id,
            status,
            dialog,
            message_text,
        ):

            conn = sqlite3.connect("bandmatch.db")

            # すでに出欠登録があるか確認
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

                # すでに登録されていたら更新
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

                # 初めてなら新規登録
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

            # メッセージを更新
            message_text.value = (
                f"出欠を「{status}」にしました！"
            )
            message_text.color = ft.Colors.GREEN

            # ==================================
            # ダイアログを閉じる
            # ==================================

            dialog.open = False
            page.update()
        # ======================================
        # 練習詳細
        # ======================================

        def show_practice_detail(practice):

            practice_id = practice[0]
            practice_date = practice[1]
            start_time = practice[2]
            end_time = practice[3]
            location = practice[4]
            content = practice[5]

            # ----------------------------------
            # 現在の出欠を取得
            # ----------------------------------

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

            # ----------------------------------
            # 出欠表示
            # ----------------------------------

            attendance_message = ft.Text(
                current_status,
                size=15,
            )

            # ----------------------------------
            # 出席状況（人数）の表示
            # ----------------------------------

            summary_counts = get_attendance_counts(
                practice_id
            )

            summary_message = ft.Text(
                build_summary_text(summary_counts),
                size=14,
            )

            # ----------------------------------
            # ダイアログを閉じる処理
            # ----------------------------------

            def close_dialog(e):
                detail_dialog.open = False
                page.update()

            # ----------------------------------
            # 出席者一覧ダイアログを表示
            # （あだ名で表示）
            # ----------------------------------

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

            # ----------------------------------
            # 出欠を保存する処理
            # ----------------------------------

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

                # 表示を更新
                attendance_message.value = (
                    f"出欠を「{status}」にしました！"
                )

                attendance_message.color = ft.Colors.GREEN

                # ------------------------------
                # 出席状況（人数）も更新
                # ------------------------------

                new_counts = get_attendance_counts(
                    practice_id
                )

                summary_message.value = (
                    build_summary_text(new_counts)
                )

                # ダイアログを閉じる
                detail_dialog.open = False

                page.update()

            # ==================================
            # ダイアログ
            # ==================================

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

                # ==================================
                # 出欠ボタン
                # ==================================

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

            # ----------------------------------
            # ダイアログを表示
            # ----------------------------------

            page.show_dialog(detail_dialog)
        # ======================================
        # カレンダー作成
        # ======================================

        def create_calendar(year, month):

            practices = get_practices()

            # ----------------------------------
            # 日付ごとに練習をまとめる
            # ----------------------------------

            practice_dict = {}

            for practice in practices:

                practice_date = practice[1]

                if practice_date not in practice_dict:
                    practice_dict[practice_date] = []

                practice_dict[practice_date].append(practice)

            # ----------------------------------
            # カレンダー
            # 月曜始まり
            # ----------------------------------

            cal = calendar.Calendar(firstweekday=0)

            calendar_rows = []

            # ==================================
            # 曜日
            # ==================================

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

            # ==================================
            # 日付
            # ==================================

            for week in cal.monthdayscalendar(year, month):

                week_controls = []

                for day in week:

                    # ----------------------------------
                    # 空白の日
                    # ----------------------------------

                    if day == 0:

                        week_controls.append(
                            ft.Container(
                                width=45,
                                height=65,
                            )
                        )

                        continue

                    # ----------------------------------
                    # YYYY/MM/DD
                    # ----------------------------------

                    date_string = (
                        f"{year:04d}/"
                        f"{month:02d}/"
                        f"{day:02d}"
                    )

                    # ----------------------------------
                    # 日付
                    # ----------------------------------

                    day_controls = [
                        ft.Text(
                            str(day),
                            size=16,
                            weight=ft.FontWeight.BOLD,
                            text_align=ft.TextAlign.CENTER,
                        )
                    ]

                    # =================================
                    # 練習日なら🎵
                    # =================================

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

                    # --------------------------
                    # 日付セル
                    # --------------------------

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
                # ----------------------------------
                # 1週間分
                # ----------------------------------

                calendar_rows.append(
                    ft.Row(
                        controls=week_controls,
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=0,
                    )
                )

            # ----------------------------------
            # カレンダー全体
            # ----------------------------------

            return ft.Column(
                controls=calendar_rows,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=3,
            )

        # ======================================
        # カレンダーの年月
        # ======================================

        today = datetime.date.today()

        current_year = today.year
        current_month = today.month

        # ======================================
        # 年の選択肢
        # ======================================

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

        # ======================================
        # 月の選択肢
        # ======================================

        month_dropdown = ft.Dropdown(
            label="月",
            value=str(current_month),
            options=[
                ft.dropdown.Option(str(month))
                for month in range(1, 13)
            ],
            width=100,
        )

        # ======================================
        # カレンダー表示を更新
        # ======================================

        def update_calendar():

            calendar_title.value = (
                f"{current_year}年{current_month}月"
            )

            calendar_container.content = create_calendar(
                current_year,
                current_month,
            )

            # Dropdownの表示も更新
            year_dropdown.value = str(current_year)
            month_dropdown.value = str(current_month)

            page.update()

        # ======================================
        # 年を変更
        # ======================================

        def year_changed(e):

            nonlocal current_year

            if e.control.value:
                current_year = int(e.control.value)

            update_calendar()

        # ======================================
        # 月を変更
        # ======================================

        def month_changed(e):

            nonlocal current_month

            if e.control.value:
                current_month = int(e.control.value)

            update_calendar()

        # ======================================
        # Dropdownにイベントを設定
        # （このFletバージョンでは on_change ではなく on_select）
        # ======================================

        year_dropdown.on_select = year_changed
        month_dropdown.on_select = month_changed
        # ======================================
        # 前月
        # ======================================

        def previous_month(e):

            nonlocal current_year
            nonlocal current_month

            current_month -= 1

            if current_month == 0:
                current_month = 12
                current_year -= 1

            update_calendar()

        # ======================================
        # 翌月
        # ======================================

        def next_month(e):

            nonlocal current_year
            nonlocal current_month

            current_month += 1

            if current_month == 13:
                current_month = 1
                current_year += 1

            update_calendar()

        # ======================================
        # カレンダータイトル
        # ======================================

        calendar_title = ft.Text(
            f"{current_year}年{current_month}月",
            size=22,
            weight=ft.FontWeight.BOLD,
        )

        # ======================================
        # 前月・翌月ボタン
        # ======================================

        previous_button = ft.ElevatedButton(
            "← 前月",
            on_click=previous_month,
        )

        next_button = ft.ElevatedButton(
            "翌月 →",
            on_click=next_month,
        )

        # ======================================
        # 年・月選択
        # ======================================

        date_selection = ft.Row(
            controls=[
                year_dropdown,
                month_dropdown,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10,
        )
        # ======================================
        # カレンダー本体
        # ======================================

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

        # ======================================
        # ホーム画面
        # ======================================

        home_title = ft.Text(
            "🎺 BandMatch",
            size=32,
            weight=ft.FontWeight.BOLD,
        )

        home_text = ft.Text(
            "ホーム",
            size=24,
        )

        login_message = ft.Text(
            "ログインしました！",
            size=16,
            color=ft.Colors.GREEN,
        )

        # ======================================
        # 管理者ボタン
        # ======================================

        admin_button = ft.ElevatedButton(
            "🎺 練習日を登録",
            width=350,
            height=50,
            on_click=lambda e: show_admin(),
        )

        # ======================================
        # ログアウト
        # ======================================

        logout_button = ft.OutlinedButton(
            "ログアウト",
            width=350,
            height=50,
            on_click=lambda e: show_login(),
        )

        # ======================================
        # ホーム表示
        # ======================================

        page.add(
            ft.Column(
                controls=[

                    home_title,

                    home_text,

                    login_message,

                    admin_button,

                    ft.Divider(),

                    ft.Text(
                        "📅 練習カレンダー",
                        size=24,
                        weight=ft.FontWeight.BOLD,
                    ),

                    # --------------------------
                    # 年・月選択
                    # --------------------------

                    date_selection,

                    # --------------------------
                    # 前月・翌月
                    # --------------------------

                    ft.Row(
                        controls=[
                            previous_button,
                            calendar_title,
                            next_button,
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=15,
                    ),

                   
                    # --------------------------
                    # カレンダー
                    # --------------------------

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
    ft.run(main)