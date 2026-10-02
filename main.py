import flet as ft
import datetime
import calendar
import hashlib
import hmac
import os

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter


# ==========================================
# Firebase 初期化（アプリ全体で1回だけ）
# ※main() の中に書くと、2人目がアクセスしたときに
# 　「もう初期化済み」エラーになるので外に書く
# ==========================================

# ★自分のPCの鍵の場所（test_firebase.py と同じパスにする）
KEY_PATH = r"C:\Users\zibat\Downloads\bandmatch2-f6a16-firebase-adminsdk-fbsvc-e2a688a715.json"

if os.path.exists(KEY_PATH):
    # 自分のPCで動かすとき
    firebase_admin.initialize_app(credentials.Certificate(KEY_PATH))
else:
    # Cloud Run で動かすとき（鍵なしで自動認証）
    firebase_admin.initialize_app()

db = firestore.client()


# ==========================================
# Firestore 用の小さな便利関数
# ==========================================

def eq(field, value):
    # where で使う「field == value」の条件
    return FieldFilter(field, "==", value)


def find(collection, field, value):
    # collection の中で field == value のドキュメントを全部取得
    return db.collection(collection).where(filter=eq(field, value)).get()


# ==========================================
# 学年コード ⇔ 表示名
# grade： 08=1年生 / 07=2年生 / 06=3年生(執行代) / 05=4年生
# ==========================================

GRADE_LABELS = {
    "08": "1年生",
    "07": "2年生",
    "06": "3年生",
    "05": "4年生",
}

# 学年ごとのパート割り振り優先度（執行代の06を最優先）
GRADE_WEIGHT = {
    "06": 4,
    "05": 3,
    "07": 2,
    "08": 1,
}

# ==========================================
# イベント関連の定数
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


# ==========================================
# ★新規：パスワードのハッシュ化
# パスワードをそのまま保存せず、元に戻せない形にして保存する
# ==========================================

def hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, 200_000
    )
    return salt.hex() + ":" + hashed.hex()


def verify_password(password, stored):
    try:
        salt_hex, _ = stored.split(":")
        salt = bytes.fromhex(salt_hex)
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


# ==========================================
# 3つのイベントと分類を最初に1回だけ作成
# events のドキュメントIDはイベントの type（teiki など）
# ==========================================

def ensure_default_events():

    for ev_type, ev_name in EVENT_TYPE_LABELS.items():

        ev_ref = db.collection("events").document(ev_type)

        if not ev_ref.get().exists:
            ev_ref.set({"name": ev_name, "type": ev_type})

        parts = [p.to_dict() for p in find("event_parts", "event_id", ev_type)]

        existing_labels = [p["label"] for p in parts]
        max_order = max((p["sort_order"] for p in parts), default=-1)

        # まだ無いデフォルト分類があれば追加する
        for label in default_categories(ev_type):
            if label not in existing_labels:
                max_order += 1
                db.collection("event_parts").add(
                    {
                        "event_id": ev_type,
                        "label": label,
                        "sort_order": max_order,
                    }
                )


ensure_default_events()


# ==========================================
# ユーザー関連
# ==========================================

def display_name(user_data):
    return user_data.get("nickname") or user_data.get("email", "")


def get_user_name(user_id):
    doc = db.collection("users").document(user_id).get()
    if not doc.exists:
        return "（不明なユーザー）"
    return display_name(doc.to_dict())


def get_club_passcode():
    # ★新規：サークルの合言葉を取得（未設定なら空文字）
    doc = db.collection("settings").document("club").get()
    if not doc.exists:
        return ""
    return doc.to_dict().get("passcode", "")


def get_all_users():
    # 部員一覧を (id, データ) のリストで返す（学年→あだ名順）
    users = [(doc.id, doc.to_dict()) for doc in db.collection("users").get()]
    users.sort(
        key=lambda x: (x[1].get("grade", ""), x[1].get("nickname", ""))
    )
    return users


# ==========================================
# 出席率を計算
# ==========================================

def calculate_attendance_rate(user_id):

    docs = find("attendance", "user_id", user_id)

    total = len(docs)

    if total == 0:
        return 0.0

    attended = sum(
        1
        for d in docs
        if d.to_dict().get("status") in ("出席", "遅刻", "早退")
    )

    return attended / total


# ==========================================
# 合宿の出欠を取得
# 未設定の場合は「来ない」扱い（安全側）
# ドキュメントIDは「合宿の種類_ユーザーID」
# ==========================================

def get_camp_attendance(camp_type, user_id):

    doc = (
        db.collection("camp_attendance")
        .document(f"{camp_type}_{user_id}")
        .get()
    )

    return bool(doc.to_dict().get("attending")) if doc.exists else False


# ==========================================
# 自動割り振りアルゴリズム
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

    song = db.collection("songs").document(song_id).get().to_dict() or {}

    capacity_map = {}

    for inst in song.get("instruments", []):
        for d, c in zip(inst["divisions"], inst["capacities"]):
            capacity_map[(inst["name"], d)] = c

    camp_type = EVENT_TYPE_CAMP[event_type]

    user_prefs = {}

    for doc in find("part_preferences", "song_id", song_id):
        p = doc.to_dict()
        user_prefs[p["user_id"]] = p.get("choices", [])

    camp_ok_map = {}
    candidates = []

    for user_id, choices in user_prefs.items():

        user_doc = db.collection("users").document(user_id).get()
        grade = user_doc.to_dict().get("grade", "") if user_doc.exists else ""
        grade_weight = GRADE_WEIGHT.get(grade, 0)

        attendance_rate = calculate_attendance_rate(user_id)

        camp_ok = get_camp_attendance(camp_type, user_id)
        camp_ok_map[user_id] = camp_ok

        for choice in choices:

            rank = choice["rank"]
            instrument = choice["instrument"]
            division = choice["division"]

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

        if any(camp_ok_map.get(m, False) for m in members):
            continue

        swap_candidates = [
            c
            for c in candidates
            if c["instrument"] == instrument
            and c["division"] == division
            and c["camp_ok"]
            and assigned.get(c["user_id"]) != key
        ]

        swap_candidates.sort(key=lambda c: c["score"], reverse=True)

        if not swap_candidates:
            # 合宿に来る候補が誰もいない場合は
            # 手動での調整が必要（そのまま残す）
            continue

        newcomer = swap_candidates[0]
        uid_new = newcomer["user_id"]
        old_key = assigned[uid_new]

        current_scores = [c for c in candidates if c["user_id"] in members]
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

    return assigned


# ==========================================
# 割り振り結果を確定保存
# ドキュメントIDは「曲ID_ユーザーID」
# ==========================================

def commit_assignments(song_id, assigned):

    batch = db.batch()

    for user_id, (instrument, division) in assigned.items():

        ref = db.collection("part_assignments").document(
            f"{song_id}_{user_id}"
        )

        batch.set(
            ref,
            {
                "song_id": song_id,
                "user_id": user_id,
                "instrument_name": instrument,
                "division": division,
            },
        )

    batch.commit()


# ==========================================
# メイン（アクセスした人ごとに1回ずつ呼ばれる）
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
    # 現在ログインしているユーザー（セッション）
    # ==========================================

    current_user_id = None
    current_user_name = ""
    is_admin = False

    # ==========================================
    # ログイン画面
    # ==========================================

    def show_login():

        nonlocal current_user_id, current_user_name, is_admin

        # ログアウト時にセッションをリセット
        current_user_id = None
        current_user_name = ""
        is_admin = False

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
                message.value = "メールアドレスを入力してください！"
                message.color = ft.Colors.RED

            elif password.value == "":
                message.value = "パスワードを入力してください！"
                message.color = ft.Colors.RED

            else:

                docs = (
                    db.collection("users")
                    .where(filter=eq("email", email.value))
                    .limit(1)
                    .get()
                )

                if docs and verify_password(
                    password.value, docs[0].to_dict().get("password")
                ):

                    user = docs[0].to_dict()

                    current_user_id = docs[0].id
                    current_user_name = display_name(user)
                    is_admin = bool(user.get("is_admin", False))

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
            on_click=lambda e: show_signup(),
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
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=20,
            )
        )

    # ==========================================
    # 新規登録画面
    # ★変更：一番最初に登録した人を自動で管理者にする
    # （テスト管理者アカウントは削除）
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

        # ★新規：サークルの合言葉
        passcode_field = ft.TextField(
            label="サークルの合言葉",
            hint_text="部員から教えてもらった合言葉",
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
                signup_message.value = "学年を選択してください！"
                signup_message.color = ft.Colors.RED

            elif name_field.value == "":
                signup_message.value = "氏名を入力してください！"
                signup_message.color = ft.Colors.RED

            elif nickname_field.value == "":
                signup_message.value = "あだ名を入力してください！"
                signup_message.color = ft.Colors.RED

            elif signup_email.value == "":
                signup_message.value = "メールアドレスを入力してください！"
                signup_message.color = ft.Colors.RED

            elif signup_password.value == "":
                signup_message.value = "パスワードを入力してください！"
                signup_message.color = ft.Colors.RED

            elif signup_password_confirm.value == "":
                signup_message.value = (
                    "パスワード（確認）を入力してください！"
                )
                signup_message.color = ft.Colors.RED

            elif signup_password.value != signup_password_confirm.value:
                signup_message.value = "パスワードが一致しません！"
                signup_message.color = ft.Colors.RED

            else:

                # 部員がまだ1人もいなければ、この人を管理者にする
                # （最初の1人だけは合言葉なしで登録できる）
                is_first_user = (
                    len(db.collection("users").limit(1).get()) == 0
                )

                club_passcode = get_club_passcode()
                entered_passcode = (passcode_field.value or "").strip()

                already = (
                    db.collection("users")
                    .where(filter=eq("email", signup_email.value))
                    .limit(1)
                    .get()
                )

                # ★新規：合言葉のチェック
                # （メールアドレスの重複チェックより先に行い、
                # 　部外者に登録済みかどうかを知られないようにする）
                if not is_first_user and club_passcode == "":

                    signup_message.value = (
                        "合言葉がまだ設定されていません。"
                        "管理者に連絡してください"
                    )
                    signup_message.color = ft.Colors.RED

                elif not is_first_user and entered_passcode != club_passcode:

                    signup_message.value = "合言葉が違います！"
                    signup_message.color = ft.Colors.RED

                elif already:

                    signup_message.value = (
                        "このメールアドレスは既に登録されています！"
                    )
                    signup_message.color = ft.Colors.RED

                else:

                    db.collection("users").add(
                        {
                            "grade": grade_dropdown.value,
                            "name": name_field.value,
                            "nickname": nickname_field.value,
                            "email": signup_email.value,
                            "password": hash_password(
                                signup_password.value
                            ),
                            "is_admin": is_first_user,
                        }
                    )

                    if is_first_user:
                        signup_message.value = (
                            "最初のアカウントなので、"
                            "管理者として作成しました！"
                        )
                    else:
                        signup_message.value = "アカウントを作成しました！"

                    signup_message.color = ft.Colors.GREEN

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
                    passcode_field,
                    signup_message,
                    create_button,
                    back_button,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
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
                message.value = "練習日を入力してください！"
                message.color = ft.Colors.RED

            elif start_time_field.value == "":
                message.value = "開始時間を入力してください！"
                message.color = ft.Colors.RED

            elif end_time_field.value == "":
                message.value = "終了時間を入力してください！"
                message.color = ft.Colors.RED

            else:

                db.collection("practices").add(
                    {
                        "date": date_field.value,
                        "start_time": start_time_field.value,
                        "end_time": end_time_field.value,
                        "location": location_field.value,
                        "content": content_field.value,
                    }
                )

                message.value = "練習日を登録しました！🎺"
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
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=15,
            )
        )

    # ==========================================
    # 合宿の出欠設定（ユーザー本人のみ）
    # ==========================================

    def show_camp_survey():

        page.clean()

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
                value=get_camp_attendance(camp_type, current_user_id),
            )

            switches[camp_type] = sw
            controls.append(sw)

        message = ft.Text("", size=14)

        def save(e):

            for camp_type, sw in switches.items():

                db.collection("camp_attendance").document(
                    f"{camp_type}_{current_user_id}"
                ).set(
                    {
                        "camp_type": camp_type,
                        "user_id": current_user_id,
                        "attending": bool(sw.value),
                    }
                )

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
    # 合宿に誰が来るか一覧（管理者・閲覧のみ）
    # ==========================================

    def show_camp_admin_view():

        if not is_admin:
            show_home()
            return

        page.clean()

        users = get_all_users()

        existing_map = {}

        for doc in db.collection("camp_attendance").get():
            c = doc.to_dict()
            existing_map[(c["camp_type"], c["user_id"])] = c["attending"]

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

            for user_id, user in users:

                name = display_name(user)

                if existing_map.get((camp_type, user_id), False):
                    attending_names.append(name)
                else:
                    not_attending_names.append(name)

            controls.append(
                ft.Text(
                    "来る："
                    + (
                        "、".join(attending_names)
                        if attending_names
                        else "（まだいません）"
                    ),
                    size=14,
                )
            )

            controls.append(
                ft.Text(
                    "来ない／未設定："
                    + (
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
    # 管理者管理（管理者の追加・削除）
    # 代替わりの際、新しい執行代を管理者にできる
    # ==========================================

    def show_admin_management():

        if not is_admin:
            show_home()
            return

        page.clean()

        users = get_all_users()

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

        for user_id, user in users:

            grade_label = GRADE_LABELS.get(user.get("grade", ""), "")

            sw = ft.Switch(
                label=f"{display_name(user)}（{grade_label}）　管理者ならON",
                value=bool(user.get("is_admin", False)),
            )

            switches[user_id] = sw
            controls.append(sw)

        message = ft.Text("", size=14)

        def save(e):

            nonlocal is_admin

            # ★追加：管理者が0人になるのを防ぐ
            if not any(sw.value for sw in switches.values()):
                message.value = "管理者を最低1人は残してください！"
                message.color = ft.Colors.RED
                page.update()
                return

            batch = db.batch()

            for user_id, sw in switches.items():
                batch.update(
                    db.collection("users").document(user_id),
                    {"is_admin": bool(sw.value)},
                )

            batch.commit()

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
    # ★新規：サークルの合言葉の設定（管理者）
    # ==========================================

    def show_passcode_settings():

        if not is_admin:
            show_home()
            return

        page.clean()

        current = get_club_passcode()

        current_text = ft.Text(
            f"現在の合言葉：{current}" if current else "現在の合言葉：（未設定）",
            size=16,
        )

        new_field = ft.TextField(
            label="新しい合言葉",
            hint_text="4文字以上",
            width=350,
        )

        message = ft.Text("", size=14)

        def save(e):

            value = (new_field.value or "").strip()

            if len(value) < 4:
                message.value = "合言葉は4文字以上にしてください！"
                message.color = ft.Colors.RED

            else:
                db.collection("settings").document("club").set(
                    {"passcode": value}
                )

                current_text.value = f"現在の合言葉：{value}"
                new_field.value = ""

                message.value = "合言葉を保存しました！"
                message.color = ft.Colors.GREEN

            page.update()

        page.add(
            ft.Column(
                controls=[
                    ft.Text(
                        "🔑 合言葉の設定",
                        size=22,
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Text(
                        "※新規登録のときに必要になります。部員にだけ伝えてください。\n"
                        "※変更しても、登録済みの部員はそのままログインできます",
                        size=12,
                        color=ft.Colors.GREY,
                    ),
                    current_text,
                    new_field,
                    ft.ElevatedButton(
                        "保存する",
                        width=350,
                        height=50,
                        on_click=save,
                    ),
                    message,
                    ft.OutlinedButton(
                        "ホームに戻る",
                        width=350,
                        height=50,
                        on_click=lambda e: show_home(),
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=15,
            )
        )

    # ==========================================
    # イベント一覧画面
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
                    on_click=(lambda e, t=ev_type: show_event_detail(t)),
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
    # イベント詳細（セトリ表示）画面
    # ==========================================

    def show_event_detail(event_type):

        page.clean()

        event = db.collection("events").document(event_type).get().to_dict()
        event_name = event["name"] if event else EVENT_TYPE_LABELS[event_type]

        parts = [
            (doc.id, doc.to_dict())
            for doc in find("event_parts", "event_id", event_type)
        ]
        parts.sort(key=lambda x: x[1]["sort_order"])

        section_controls = []

        # 「通常」カテゴリの曲は 1. 2. 3. と通し番号で表示
        normal_song_number = 1

        for part_id, part in parts:

            label = part["label"]

            songs = [
                (doc.id, doc.to_dict())
                for doc in find("songs", "event_part_id", part_id)
            ]
            songs.sort(key=lambda x: x[1]["sort_order"])

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

            for song_id, song in songs:

                if label == "通常":
                    display_text = f"{normal_song_number}. {song['title']}"
                    normal_song_number += 1
                else:
                    display_text = f"・{song['title']}"

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
    # 曲を追加するダイアログ（管理者）
    # パート編成は曲のドキュメントの中に
    # instruments（リスト）としてまとめて保存する
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

                if name_field.value == "" or divisions_field.value == "":
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
                    {
                        "name": name_field.value,
                        "divisions": divisions,
                        "capacities": capacities,
                    }
                )

            if not instruments_data:
                message.value = "楽器を1つ以上入力してください！"
                message.color = ft.Colors.RED
                page.update()
                return

            existing_songs = find("songs", "event_part_id", event_part_id)

            max_order = max(
                (s.to_dict()["sort_order"] for s in existing_songs),
                default=-1,
            )

            db.collection("songs").add(
                {
                    "event_part_id": event_part_id,
                    "title": title_field.value,
                    "sort_order": max_order + 1,
                    "instruments": instruments_data,
                }
            )

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
    # 曲の詳細画面
    # ==========================================

    def show_song_detail(song_id, event_type):

        page.clean()

        song = db.collection("songs").document(song_id).get().to_dict() or {}

        title = ft.Text(
            f"🎵 {song.get('title', '')}",
            size=26,
            weight=ft.FontWeight.BOLD,
        )

        part_controls = [
            ft.Text("パート編成", size=18, weight=ft.FontWeight.BOLD)
        ]

        for inst in song.get("instruments", []):

            detail = " / ".join(
                f"{d}（定員{c}）"
                for d, c in zip(inst["divisions"], inst["capacities"])
            )

            part_controls.append(
                ft.Text(f"・{inst['name']}：{detail}", size=15)
            )

        result_button = ft.OutlinedButton(
            "📊 決定結果を見る",
            width=350,
            height=50,
            on_click=(lambda e: show_part_results(song_id, event_type)),
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
                    on_click=(lambda e: show_part_admin(song_id, event_type)),
                )
            )

        else:

            action_buttons.append(
                ft.ElevatedButton(
                    "🗳 パート希望を出す",
                    width=350,
                    height=50,
                    on_click=(lambda e: show_part_survey(song_id, event_type)),
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
    # パート希望調査（ユーザー）
    # 第1〜第4希望を choices（リスト）としてまとめて保存
    # ドキュメントIDは「曲ID_ユーザーID」
    # ==========================================

    def show_part_survey(song_id, event_type):

        page.clean()

        song = db.collection("songs").document(song_id).get().to_dict() or {}

        pref_ref = db.collection("part_preferences").document(
            f"{song_id}_{current_user_id}"
        )
        pref_doc = pref_ref.get()

        existing_choices = (
            pref_doc.to_dict().get("choices", []) if pref_doc.exists else []
        )

        options = []

        for inst in song.get("instruments", []):
            for d in inst["divisions"]:
                options.append(
                    ft.dropdown.Option(
                        key=f"{inst['name']}|{d}",
                        text=f"{inst['name']}　{d}",
                    )
                )

        options.append(ft.dropdown.Option(key="|降り", text="降り"))

        existing_map = {
            c["rank"]: f"{c['instrument']}|{c['division']}"
            for c in existing_choices
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
                message.value = "同じ組み合わせを複数選ぶことはできません！"
                message.color = ft.Colors.RED
                page.update()
                return

            choices = []

            for rank, value in enumerate(values, start=1):
                instrument, division = value.split("|")
                choices.append(
                    {
                        "rank": rank,
                        "instrument": instrument,
                        "division": division,
                    }
                )

            pref_ref.set(
                {
                    "song_id": song_id,
                    "user_id": current_user_id,
                    "choices": choices,
                }
            )

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
                        f"🗳 {song.get('title', '')} のパート希望",
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
    # パート決め画面（管理者）
    # 希望確認 → 自動決定 → 結果確定
    # ==========================================

    def show_part_admin(song_id, event_type):

        if not is_admin:
            show_home()
            return

        page.clean()

        song = db.collection("songs").document(song_id).get().to_dict() or {}

        pref_controls = [
            ft.Text("📋 希望確認", size=18, weight=ft.FontWeight.BOLD)
        ]

        prefs = [d.to_dict() for d in find("part_preferences", "song_id", song_id)]

        if not prefs:
            pref_controls.append(
                ft.Text("まだ希望が提出されていません", size=14)
            )

        for p in prefs:

            name = get_user_name(p["user_id"])

            choice_text = " / ".join(
                f"第{c['rank']}希望:{c['instrument']} {c['division']}"
                for c in sorted(p.get("choices", []), key=lambda c: c["rank"])
            )

            pref_controls.append(
                ft.Text(f"・{name}：{choice_text}", size=13)
            )

        preview_column = ft.Column(spacing=5)
        message = ft.Text("", size=14)

        computed_assignment = {"data": None}

        def run_auto_assign(e):

            message.value = "計算中です…"
            message.color = ft.Colors.GREY
            page.update()

            assigned = auto_assign_song(song_id, event_type)
            computed_assignment["data"] = assigned

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

                names = [get_user_name(uid) for uid in uids]

                label = (
                    "降り" if division == "降り" else f"{instrument} {division}"
                )

                preview_column.controls.append(
                    ft.Text(f"【{label}】{', '.join(names)}", size=14)
                )

            message.value = (
                "自動決定を計算しました。内容を確認して"
                "「結果を確定する」を押してください。"
            )
            message.color = ft.Colors.BLUE
            page.update()

        def confirm_result(e):

            if computed_assignment["data"] is None:
                message.value = "先に「🤖 自動決定を実行」を押してください！"
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
                        f"⚙ {song.get('title', '')} のパート決め（管理者）",
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
    # パート決定結果（ユーザー・管理者共通）
    # ==========================================

    def show_part_results(song_id, event_type):

        page.clean()

        song = db.collection("songs").document(song_id).get().to_dict() or {}

        results = [
            d.to_dict() for d in find("part_assignments", "song_id", song_id)
        ]

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

            for r in results:
                name = get_user_name(r["user_id"])
                label = (
                    "降り"
                    if r["division"] == "降り"
                    else f"{r['instrument_name']} {r['division']}"
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
                        f"📊 {song.get('title', '')} のパート決定結果",
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

            # (id, date, start_time, end_time, location, content) の形で返す
            rows = []

            for doc in db.collection("practices").get():
                p = doc.to_dict()
                rows.append(
                    (
                        doc.id,
                        p.get("date", ""),
                        p.get("start_time", ""),
                        p.get("end_time", ""),
                        p.get("location", ""),
                        p.get("content", ""),
                    )
                )

            rows.sort(key=lambda r: r[1])

            return rows

        def get_attendance_counts(practice_id):

            docs = find("attendance", "practice_id", practice_id)

            total_users = len(db.collection("users").get())

            counts = {
                "出席": 0,
                "欠席": 0,
                "遅刻": 0,
                "早退": 0,
            }

            for d in docs:
                status = d.to_dict().get("status")
                if status in counts:
                    counts[status] += 1

            answered = sum(counts.values())

            counts["未回答"] = max(total_users - answered, 0)

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

            display_rows = []

            for d in find("attendance", "practice_id", practice_id):
                a = d.to_dict()
                display_rows.append((get_user_name(a["user_id"]), a["status"]))

            display_rows.sort(key=lambda r: r[1])

            return display_rows

        def show_practice_detail(practice):

            practice_id = practice[0]
            practice_date = practice[1]
            start_time = practice[2]
            end_time = practice[3]
            location = practice[4]
            content = practice[5]

            # 出欠のドキュメントIDは「練習ID_ユーザーID」
            attendance_ref = db.collection("attendance").document(
                f"{practice_id}_{current_user_id}"
            )

            attendance = attendance_ref.get()

            if attendance.exists:
                current_status = (
                    f"現在の出欠：{attendance.to_dict()['status']}"
                )
            else:
                current_status = "現在の出欠：未回答"

            attendance_message = ft.Text(
                current_status,
                size=15,
            )

            summary_message = ft.Text(
                build_summary_text(get_attendance_counts(practice_id)),
                size=14,
            )

            def close_dialog(e):
                detail_dialog.open = False
                page.update()

            def show_attendees_list(e):

                attendee_rows = get_attendance_list(practice_id)

                if attendee_rows:

                    list_controls = [
                        ft.Text(
                            f"{status}：{name}",
                            size=14,
                        )
                        for name, status in attendee_rows
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
                    actions_alignment=ft.MainAxisAlignment.CENTER,
                )

                page.show_dialog(attendees_dialog)

            def save_status(status):

                attendance_ref.set(
                    {
                        "practice_id": practice_id,
                        "user_id": current_user_id,
                        "status": status,
                    }
                )

                attendance_message.value = f"出欠を「{status}」にしました！"
                attendance_message.color = ft.Colors.GREEN

                summary_message.value = build_summary_text(
                    get_attendance_counts(practice_id)
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
                        ft.Text(f"📅 {practice_date}", size=17),
                        ft.Text(f"⏰ {start_time} ～ {end_time}", size=17),
                        ft.Text(f"📍 {location}", size=17),
                        ft.Divider(),
                        ft.Text(
                            "練習内容",
                            size=17,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text(
                            content if content else "（登録なし）",
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
                practice_dict.setdefault(practice[1], []).append(practice)

            cal = calendar.Calendar(firstweekday=0)

            calendar_rows = []

            weekday_cells = []

            for label, color in [
                ("月", None),
                ("火", None),
                ("水", None),
                ("木", None),
                ("金", None),
                ("土", ft.Colors.BLUE),
                ("日", ft.Colors.RED),
            ]:
                weekday_cells.append(
                    ft.Container(
                        content=ft.Text(
                            label,
                            text_align=ft.TextAlign.CENTER,
                            color=color,
                        ),
                        width=45,
                    )
                )

            calendar_rows.append(
                ft.Row(
                    controls=weekday_cells,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=0,
                )
            )

            for week in cal.monthdayscalendar(year, month):

                week_controls = []

                for day in week:

                    if day == 0:
                        week_controls.append(
                            ft.Container(width=45, height=65)
                        )
                        continue

                    date_string = f"{year:04d}/{month:02d}/{day:02d}"

                    day_controls = [
                        ft.Text(
                            str(day),
                            size=16,
                            weight=ft.FontWeight.BOLD,
                            text_align=ft.TextAlign.CENTER,
                        )
                    ]

                    for practice in practice_dict.get(date_string, []):

                        day_controls.append(
                            ft.TextButton(
                                content=ft.Text("🎵", size=18),
                                on_click=lambda e, p=practice:
                                    show_practice_detail(p),
                            )
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
                            alignment=ft.Alignment(0, 0),
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
                for year in range(current_year - 5, current_year + 6)
            ],
            width=120,
        )

        month_dropdown = ft.Dropdown(
            label="月",
            value=str(current_month),
            options=[
                ft.dropdown.Option(str(month)) for month in range(1, 13)
            ],
            width=100,
        )

        def update_calendar():

            calendar_title.value = f"{current_year}年{current_month}月"

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

            nonlocal current_year, current_month

            current_month -= 1

            if current_month == 0:
                current_month = 12
                current_year -= 1

            update_calendar()

        def next_month(e):

            nonlocal current_year, current_month

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
            controls=[year_dropdown, month_dropdown],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10,
        )

        calendar_container = ft.Container(
            content=create_calendar(current_year, current_month),
            padding=10,
            border=ft.Border.all(1, "#CCCCCC"),
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

        events_button = ft.ElevatedButton(
            "🎪 イベント",
            width=350,
            height=50,
            on_click=lambda e: show_events(),
        )

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
                    "🔑 合言葉の設定",
                    width=350,
                    height=50,
                    on_click=lambda e: show_passcode_settings(),
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
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=15,
            )
        )

    # ==========================================
    # 最初はログイン画面
    # ==========================================

    show_login()


# ==========================================
# アプリ起動（ブラウザで開く）
# ==========================================

if __name__ == "__main__":
    ft.run(
        main,
        assets_dir="assets",
        view=ft.AppView.WEB_BROWSER,
        port=int(os.environ.get("PORT", 8550)),
    )