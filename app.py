from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "khl_playoff.db"))

db = SQLAlchemy()

ROUND_WEIGHTS = {"R1": 1.0, "QF": 1.25, "SF": 1.6, "F": 2.2}
ROUND_LABELS = {"R1": "1/8 финала", "QF": "1/4 финала", "SF": "1/2 финала", "F": "Финал"}
CONFERENCE_LABELS = {"W": "Запад", "E": "Восток"}
LOGIN_RE = re.compile(r"^[a-zA-Z0-9_]{3,24}$")
DETAILED_ROUNDS = {"SF", "F"}

TEAM_LOGO_FILES = {
    "Авангард": "avangard.png",
    "Металлург": "metallurg.png",
    "Ак Барс": "ak_bars.png",
    "Трактор": "traktor.png",
    "Сибирь": "sibir.png",
    "Салават Юлаев": "salavat_yulaev.png",
    "Автомобилист": "avtomobilist.png",
    "Нефтехимик": "neftekhimik.png",
    "Северсталь": "severstal.png",
    "Динамо Мн": "dynamo_minsk.png",
    "Динамо Минск": "dynamo_minsk.png",
    "ЦСКА": "cska.gif",
    "Динамо М": "dynamo_moscow.png",
    "Динамо Москва": "dynamo_moscow.png",
    "Спартак": "spartak.png",
    "Торпедо": "torpedo.png",
    "СКА": "ska.png",
    "Локомотив": "lokomotiv.gif",
}



def team_logo_url(team_name: str) -> str:
    logo_file = TEAM_LOGO_FILES.get(team_name, "default.svg")
    logo_path = BASE_DIR / "static" / "team_logos" / logo_file
    if not logo_path.exists():
        logo_file = "default.svg"
    return url_for("static", filename=f"team_logos/{logo_file}")





def detailed_predictions_enabled(round_code: str) -> bool:
    return round_code in DETAILED_ROUNDS


def parse_locked_games(serialized: str) -> set[int]:
    result: set[int] = set()
    for item in serialized.split(","):
        value = item.strip()
        if value.isdigit():
            idx = int(value)
            if 1 <= idx <= 7:
                result.add(idx)
    return result


def serialize_locked_games(locked_games: set[int]) -> str:
    return ",".join(str(idx) for idx in sorted(locked_games))


def validate_outcomes_sequence(outcomes: list[str], wins_a: int, wins_b: int) -> tuple[bool, str]:
    if outcomes.count("A") != wins_a or outcomes.count("B") != wins_b:
        return False, "Победы по матчам должны совпадать с итоговым счетом серии"

    a_wins = 0
    b_wins = 0
    for idx, outcome in enumerate(outcomes, start=1):
        if outcome == "A":
            a_wins += 1
        elif outcome == "B":
            b_wins += 1
        else:
            return False, "Некорректная последовательность исходов"

        if idx < len(outcomes) and (a_wins == 4 or b_wins == 4):
            return False, "Серия не может продолжаться после 4-й победы команды"

    if a_wins != wins_a or b_wins != wins_b:
        return False, "Победы по матчам должны совпадать с итоговым счетом серии"
    return True, ""

def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="change-me",
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{DB_PATH}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    with app.app_context():
        db.create_all()
        ensure_schema_compatibility()
        seed_matches()

    register_routes(app)
    return app


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    is_blocked = db.Column(db.Boolean, nullable=False, default=False)
    display_name = db.Column(db.String(120), nullable=False, default="")
    favorite_team = db.Column(db.String(120), nullable=False, default="Авангард")
    bio = db.Column(db.String(255), nullable=False, default="")


class PlayoffSeries(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_a = db.Column(db.String(120), nullable=False)
    team_b = db.Column(db.String(120), nullable=False)
    conference = db.Column(db.String(1), nullable=False, default="W")
    round_code = db.Column(db.String(8), nullable=False, default="R1")
    prediction_deadline = db.Column(db.DateTime)
    locked_game_indices = db.Column(db.String(32), nullable=False, default="")

    @property
    def conference_label(self) -> str:
        return CONFERENCE_LABELS.get(self.conference, self.conference)

    @property
    def round_label(self) -> str:
        return ROUND_LABELS.get(self.round_code, self.round_code)


class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    home_team = db.Column(db.String(120), nullable=False)
    away_team = db.Column(db.String(120), nullable=False)
    kickoff = db.Column(db.DateTime, nullable=False)
    conference = db.Column(db.String(1), nullable=False, default="W")
    round_code = db.Column(db.String(8), nullable=False, default="R1")
    series_id = db.Column(db.Integer, db.ForeignKey("playoff_series.id"))
    home_score = db.Column(db.Integer)
    away_score = db.Column(db.Integer)

    series = db.relationship("PlayoffSeries", backref=db.backref("matches", lazy=True))

    @property
    def is_finished(self) -> bool:
        return self.home_score is not None and self.away_score is not None

    @property
    def round_label(self) -> str:
        return ROUND_LABELS.get(self.round_code, self.round_code)

    @property
    def conference_label(self) -> str:
        return CONFERENCE_LABELS.get(self.conference, self.conference)


class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=False)
    predicted_home = db.Column(db.Integer, nullable=False)
    predicted_away = db.Column(db.Integer, nullable=False)

    user = db.relationship("User", backref=db.backref("predictions", lazy=True))
    match = db.relationship("Match", backref=db.backref("predictions", lazy=True))

    __table_args__ = (db.UniqueConstraint("user_id", "match_id", name="uq_user_match"),)


class SeriesPrediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    series_id = db.Column(db.Integer, db.ForeignKey("playoff_series.id"), nullable=False)
    predicted_wins_a = db.Column(db.Integer, nullable=False)
    predicted_wins_b = db.Column(db.Integer, nullable=False)
    game_outcomes = db.Column(db.String(32), nullable=False, default="")  # CSV of A/B outcomes by games
    game_scores = db.Column(db.String(96), nullable=False, default="")  # CSV of a:b scores by games (team_a perspective)

    user = db.relationship("User", backref=db.backref("series_predictions", lazy=True))
    series = db.relationship("PlayoffSeries", backref=db.backref("series_predictions", lazy=True))

    __table_args__ = (db.UniqueConstraint("user_id", "series_id", name="uq_user_series"),)


def ensure_schema_compatibility() -> None:
    inspector = db.inspect(db.engine)
    user_columns = {col["name"] for col in inspector.get_columns("user")}
    match_columns = {col["name"] for col in inspector.get_columns("match")}
    series_columns = {col["name"] for col in inspector.get_columns("playoff_series")}
    series_prediction_columns = {col["name"] for col in inspector.get_columns("series_prediction")}

    if "is_admin" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
    if "is_blocked" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN is_blocked BOOLEAN DEFAULT 0"))
    if "display_name" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN display_name VARCHAR(120) DEFAULT ''"))
    if "favorite_team" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN favorite_team VARCHAR(120) DEFAULT 'Авангард'"))
    if "bio" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN bio VARCHAR(255) DEFAULT ''"))

    if "conference" not in match_columns:
        db.session.execute(text("ALTER TABLE match ADD COLUMN conference VARCHAR(1) DEFAULT 'W'"))
    if "series_id" not in match_columns:
        db.session.execute(text("ALTER TABLE match ADD COLUMN series_id INTEGER"))
    if "prediction_deadline" not in series_columns:
        db.session.execute(text("ALTER TABLE playoff_series ADD COLUMN prediction_deadline DATETIME"))
    if "locked_game_indices" not in series_columns:
        db.session.execute(text("ALTER TABLE playoff_series ADD COLUMN locked_game_indices VARCHAR(32) DEFAULT ''"))
    if "game_scores" not in series_prediction_columns:
        db.session.execute(text("ALTER TABLE series_prediction ADD COLUMN game_scores VARCHAR(96) DEFAULT ''"))

    db.session.commit()

    for user in User.query.all():
        if not user.display_name:
            user.display_name = user.username
    db.session.commit()


def seed_matches() -> None:
    if Match.query.count() > 0 or PlayoffSeries.query.count() > 0:
        return

    s1 = PlayoffSeries(team_a="СКА", team_b="Локомотив", conference="W", round_code="R1", prediction_deadline=datetime(2026, 3, 14, 18, 0))
    s2 = PlayoffSeries(team_a="Металлург", team_b="Авангард", conference="E", round_code="R1", prediction_deadline=datetime(2026, 3, 15, 18, 0))
    db.session.add_all([s1, s2])
    db.session.flush()

    matches = [
        Match(home_team="СКА", away_team="Локомотив", kickoff=datetime(2026, 3, 15, 19, 30), conference="W", round_code="R1", series_id=s1.id),
        Match(home_team="Металлург", away_team="Авангард", kickoff=datetime(2026, 3, 16, 19, 30), conference="E", round_code="R1", series_id=s2.id),
    ]
    db.session.add_all(matches)
    db.session.commit()


def current_user() -> User | None:
    user_id = session.get("user_id")
    return db.session.get(User, user_id) if user_id else None


def _sign(value: int) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def is_valid_login(value: str) -> bool:
    return bool(LOGIN_RE.fullmatch(value))


def score_details(prediction: Prediction) -> dict:
    """Legacy per-match scoring (kept for backward compatibility)."""
    match = prediction.match
    if not match.is_finished:
        return {"total": 0, "weight": ROUND_WEIGHTS.get(match.round_code, 1.0), "base": 0, "components": []}

    pred_home, pred_away = prediction.predicted_home, prediction.predicted_away
    real_home, real_away = match.home_score, match.away_score
    pred_diff, real_diff = pred_home - pred_away, real_home - real_away

    components: list[str] = []
    base_points = 0

    if _sign(pred_diff) == _sign(real_diff):
        base_points += 2
        components.append("угадан исход")
    if pred_home == real_home and pred_away == real_away:
        base_points += 4
        components.append("точный счет")

    weight = ROUND_WEIGHTS.get(match.round_code, 1.0)
    return {"total": int(round(base_points * weight)), "weight": weight, "base": base_points, "components": components}


def score_prediction(prediction: Prediction) -> int:
    return score_details(prediction)["total"]


def parse_game_scores(serialized: str) -> list[tuple[int, int]]:
    scores: list[tuple[int, int]] = []
    for raw in serialized.split(","):
        value = raw.strip()
        if not value:
            continue
        if ":" not in value:
            continue
        left, right = value.split(":", 1)
        if not left.isdigit() or not right.isdigit():
            continue
        scores.append((int(left), int(right)))
    return scores


def serialize_game_scores(scores: list[tuple[int, int]]) -> str:
    return ",".join(f"{home}:{away}" for home, away in scores)


def series_actual(series: PlayoffSeries) -> dict:
    games = sorted(series.matches, key=lambda m: m.kickoff)
    outcomes: list[str] = []
    scores: list[tuple[int, int]] = []
    wins_a = 0
    wins_b = 0

    for game in games:
        if not game.is_finished:
            continue
        if game.home_team == series.team_a:
            a_goals, b_goals = game.home_score, game.away_score
        else:
            a_goals, b_goals = game.away_score, game.home_score

        scores.append((a_goals, b_goals))
        if a_goals == b_goals:
            continue

        winner = "A" if a_goals > b_goals else "B"
        outcomes.append(winner)
        if winner == "A":
            wins_a += 1
        else:
            wins_b += 1

    finished = wins_a == 4 or wins_b == 4
    winner = "A" if wins_a > wins_b else "B" if wins_b > wins_a else None
    return {
        "wins_a": wins_a,
        "wins_b": wins_b,
        "outcomes": outcomes,
        "scores": scores,
        "finished": finished,
        "winner": winner,
    }


def score_series_prediction(prediction: SeriesPrediction) -> dict:
    series = prediction.series or db.session.get(PlayoffSeries, prediction.series_id)
    if not series:
        return {"total": 0, "base": 0, "weight": 1.0, "components": []}

    actual = series_actual(series)
    weight = ROUND_WEIGHTS.get(series.round_code, 1.0)
    if not actual["finished"]:
        return {"total": 0, "base": 0, "weight": weight, "components": []}

    base = 0
    components: list[str] = []

    predicted_winner = "A" if prediction.predicted_wins_a > prediction.predicted_wins_b else "B"
    if predicted_winner == actual["winner"]:
        base += 3
        components.append("угадан победитель серии")

    if prediction.predicted_wins_a == actual["wins_a"] and prediction.predicted_wins_b == actual["wins_b"]:
        base += 4
        components.append("точный счет серии")

    predicted_scores = parse_game_scores(prediction.game_scores)
    exact_match_hits = 0
    for idx, real_score in enumerate(actual["scores"]):
        if idx < len(predicted_scores) and predicted_scores[idx] == real_score:
            base += 1
            exact_match_hits += 1

    if exact_match_hits > 0:
        components.append(f"+{exact_match_hits} за точные счета матчей")

    total = int(round(base * weight))
    return {"total": total, "base": base, "weight": weight, "components": components}


def leaderboard() -> list[dict]:
    result = []
    for user in User.query.order_by(User.display_name, User.username).all():
        points = sum(score_series_prediction(prediction)["total"] for prediction in user.series_predictions)
        exact_hits = 0
        for prediction in user.series_predictions:
            actual = series_actual(prediction.series)
            if actual["finished"] and prediction.predicted_wins_a == actual["wins_a"] and prediction.predicted_wins_b == actual["wins_b"]:
                exact_hits += 1

        result.append(
            {
                "display_name": user.display_name,
                "username": user.username,
                "points": points,
                "exact_hits": exact_hits,
                "user_id": user.id,
            }
        )

    return sorted(result, key=lambda item: (item["points"], item["exact_hits"], item["display_name"]), reverse=True)


def user_rank(user_id: int) -> int:
    for idx, row in enumerate(leaderboard(), start=1):
        if row["user_id"] == user_id:
            return idx
    return 0


def group_matches_by_conference(matches: list[Match]) -> dict[str, list[Match]]:
    grouped: dict[str, list[Match]] = {"W": [], "E": []}
    for match in matches:
        grouped.setdefault(match.conference, []).append(match)
    return grouped


def build_bracket_data() -> dict:
    data: dict[str, dict[str, list[dict]]] = {"W": defaultdict(list), "E": defaultdict(list)}
    round_order = ["R1", "QF", "SF", "F"]
    round_prefix = {"R1": "EF", "QF": "QF", "SF": "SF", "F": "F"}

    # Подробные данные серий + табличный вид по раундам
    round_rows: dict[str, list[dict]] = {code: [] for code in round_order}
    round_idx: dict[str, int] = {code: 1 for code in round_order}

    for series in PlayoffSeries.query.order_by(PlayoffSeries.round_code, PlayoffSeries.conference, PlayoffSeries.id).all():
        wins = {series.team_a: 0, series.team_b: 0}
        goals = {series.team_a: 0, series.team_b: 0}
        game_cols_a = ["" for _ in range(7)]
        game_cols_b = ["" for _ in range(7)]
        games = sorted(series.matches, key=lambda m: m.kickoff)

        for idx, game in enumerate(games[:7]):
            if not game.is_finished:
                continue

            # счет в перспективе team_a / team_b
            if game.home_team == series.team_a:
                a_goals, b_goals = game.home_score, game.away_score
            else:
                a_goals, b_goals = game.away_score, game.home_score

            game_cols_a[idx] = f"{a_goals}:{b_goals}"
            game_cols_b[idx] = f"{b_goals}:{a_goals}"
            goals[series.team_a] += a_goals
            goals[series.team_b] += b_goals

            if a_goals > b_goals:
                wins[series.team_a] += 1
            elif b_goals > a_goals:
                wins[series.team_b] += 1

        winner = series.team_a if wins[series.team_a] >= wins[series.team_b] else series.team_b

        data[series.conference][series.round_code].append(
            {
                "team_a": series.team_a,
                "team_b": series.team_b,
                "wins": wins,
                "games": games,
                "winner": winner,
            }
        )

        label = f"{round_prefix.get(series.round_code, series.round_code)}{round_idx[series.round_code]}"
        round_idx[series.round_code] += 1
        round_rows[series.round_code].append(
            {
                "label": label,
                "team_a": series.team_a,
                "team_b": series.team_b,
                "games_a": game_cols_a,
                "games_b": game_cols_b,
                "wins_a": wins[series.team_a],
                "wins_b": wins[series.team_b],
                "goals_a": goals[series.team_a],
                "goals_b": goals[series.team_b],
                "winner": winner,
            }
        )

    data["round_rows"] = round_rows
    data["round_order"] = round_order
    return data



def series_results_snapshot(series: PlayoffSeries) -> dict:
    games = sorted(series.matches, key=lambda item: item.kickoff)
    scores: list[tuple[int, int]] = []
    wins_a = 0
    wins_b = 0

    for game in games:
        if not game.is_finished:
            continue
        if game.home_team == series.team_a:
            a_goals, b_goals = game.home_score, game.away_score
        else:
            a_goals, b_goals = game.away_score, game.home_score
        scores.append((a_goals, b_goals))
        if a_goals > b_goals:
            wins_a += 1
        elif b_goals > a_goals:
            wins_b += 1

    return {
        "wins_a": wins_a,
        "wins_b": wins_b,
        "scores": scores,
    }


def game_teams_by_index(series: PlayoffSeries, game_index: int) -> tuple[str, str]:
    home_for_a = game_index in {1, 2, 5, 7}
    if home_for_a:
        return series.team_a, series.team_b
    return series.team_b, series.team_a

def register_routes(app: Flask) -> None:
    @app.context_processor
    def inject_user():
        return {"current_user": current_user(), "team_logo_url": team_logo_url}

    @app.get("/")
    def index():
        return redirect(url_for("login" if not current_user() else "cabinet"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not username or not password:
                flash("Введите логин и пароль")
                return redirect(url_for("register"))
            if not is_valid_login(username):
                flash("Логин должен быть 3-24 символа: латиница, цифры и _")
                return redirect(url_for("register"))
            if User.query.filter_by(username=username).first():
                flash("Такой пользователь уже существует")
                return redirect(url_for("register"))

            is_admin = request.form.get("admin_key") == os.getenv("ADMIN_KEY", "OMSK")
            user = User(username=username, password_hash=generate_password_hash(password), display_name=username, is_admin=is_admin)
            db.session.add(user)
            db.session.commit()
            flash("Регистрация завершена. Войдите в аккаунт")
            return redirect(url_for("login"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter_by(username=username).first()
            if not user or not check_password_hash(user.password_hash, password):
                flash("Неверный логин или пароль")
                return redirect(url_for("login"))
            if user.is_blocked:
                flash("Аккаунт заблокирован администратором")
                return redirect(url_for("login"))
            session["user_id"] = user.id
            return redirect(url_for("cabinet"))
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/cabinet", methods=["GET", "POST"])
    def cabinet():
        user = current_user()
        if not user:
            return redirect(url_for("login"))

        if request.method == "POST":
            display_name = request.form.get("display_name", "").strip()

            if not is_valid_login(display_name):
                flash("Отображаемое имя должно быть 3-24 символа: латиница, цифры и _")
                return redirect(url_for("cabinet"))

            existing = User.query.filter(User.display_name == display_name, User.id != user.id).first()
            if existing:
                flash("Отображаемое имя уже занято")
                return redirect(url_for("cabinet"))

            user.display_name = display_name
            db.session.commit()
            flash("Профиль обновлен")
            return redirect(url_for("cabinet"))

        points = sum(score_series_prediction(prediction)["total"] for prediction in user.series_predictions)
        exact_hits = sum(
            1
            for prediction in user.series_predictions
            if (actual := series_actual(prediction.series))["finished"]
            and prediction.predicted_wins_a == actual["wins_a"]
            and prediction.predicted_wins_b == actual["wins_b"]
        )
        return render_template(
            "cabinet.html",
            points=points,
            rank=user_rank(user.id),
            total_users=User.query.count(),
            predictions_count=len(user.series_predictions),
            exact_hits=exact_hits,
        )

    @app.route("/predictions", methods=["GET", "POST"])
    def predictions():
        user = current_user()
        if not user:
            return redirect(url_for("login"))

        if request.method == "POST":
            series_id = int(request.form["series_id"])
            series = PlayoffSeries.query.get_or_404(series_id)
            focus_url = f"{url_for('predictions')}#series-{series.id}"

            if series.prediction_deadline and datetime.now() > series.prediction_deadline:
                flash("Дедлайн прогноза по серии уже прошел")
                return redirect(focus_url)

            wins_a = int(request.form["predicted_wins_a"])
            wins_b = int(request.form["predicted_wins_b"])
            if 4 not in (wins_a, wins_b):
                flash("Серия играется до 4 побед — одна из команд должна иметь 4")
                return redirect(focus_url)
            if wins_a < 0 or wins_b < 0 or wins_a > 4 or wins_b > 4:
                flash("Некорректный счет серии")
                return redirect(focus_url)

            games_count = wins_a + wins_b
            if games_count > 7:
                flash("В серии максимум 7 матчей")
                return redirect(focus_url)

            prediction = SeriesPrediction.query.filter_by(user_id=user.id, series_id=series.id).first()
            detailed_enabled = detailed_predictions_enabled(series.round_code)

            serialized = ""
            serialized_scores = ""

            if detailed_enabled:
                raw_home_scores = request.form.getlist("game_home_scores")[:games_count]
                raw_away_scores = request.form.getlist("game_away_scores")[:games_count]
                if len(raw_home_scores) != games_count or len(raw_away_scores) != games_count:
                    flash("Заполните точные счета всех матчей серии")
                    return redirect(focus_url)

                game_scores: list[tuple[int, int]] = []
                outcomes: list[str] = []
                locked_games = parse_locked_games(series.locked_game_indices)
                existing_scores = parse_game_scores(prediction.game_scores) if prediction else []

                for idx, (raw_home, raw_away) in enumerate(zip(raw_home_scores, raw_away_scores), start=1):
                    if not raw_home.isdigit() or not raw_away.isdigit():
                        flash(f"Матч {idx}: укажите счет неотрицательными числами")
                        return redirect(focus_url)
                    home_score = int(raw_home)
                    away_score = int(raw_away)
                    if home_score == away_score:
                        flash(f"Матч {idx}: в плей-офф не может быть ничьи")
                        return redirect(focus_url)

                    if idx in locked_games:
                        if idx <= len(existing_scores):
                            prev_home, prev_away = existing_scores[idx - 1]
                            if (home_score, away_score) != (prev_home, prev_away):
                                flash(f"Матч {idx} заблокирован для редактирования")
                                return redirect(focus_url)
                        else:
                            flash(f"Матч {idx} уже заблокирован для новых прогнозов")
                            return redirect(focus_url)

                    game_scores.append((home_score, away_score))
                    outcomes.append("A" if home_score > away_score else "B")

                valid_sequence, message = validate_outcomes_sequence(outcomes, wins_a, wins_b)
                if not valid_sequence:
                    flash(message)
                    return redirect(focus_url)

                serialized = ",".join(outcomes)
                serialized_scores = serialize_game_scores(game_scores)

            if prediction:
                prediction.predicted_wins_a = wins_a
                prediction.predicted_wins_b = wins_b
                prediction.game_outcomes = serialized
                prediction.game_scores = serialized_scores
                flash("Прогноз по серии обновлен")
            else:
                db.session.add(
                    SeriesPrediction(
                        user_id=user.id,
                        series_id=series.id,
                        predicted_wins_a=wins_a,
                        predicted_wins_b=wins_b,
                        game_outcomes=serialized,
                        game_scores=serialized_scores,
                    )
                )
                flash("Прогноз по серии сохранен")
            db.session.commit()
            return redirect(focus_url)

        series_list = PlayoffSeries.query.order_by(PlayoffSeries.round_code, PlayoffSeries.conference, PlayoffSeries.id).all()
        prediction_by_series = {p.series_id: p for p in user.series_predictions}
        locked_games_by_series = {series.id: parse_locked_games(series.locked_game_indices) for series in series_list}
        return render_template(
            "predictions.html",
            series_list=series_list,
            prediction_by_series=prediction_by_series,
            locked_games_by_series=locked_games_by_series,
            detailed_rounds=DETAILED_ROUNDS,
            conference_labels=CONFERENCE_LABELS,
            round_labels=ROUND_LABELS,
            now=datetime.now(),
        )

    @app.get("/results")
    def results():
        user = current_user()
        if not user:
            return redirect(url_for("login"))
        finished_matches = Match.query.filter(Match.home_score.isnot(None)).order_by(Match.kickoff).all()
        return render_template(
            "results.html",
            finished_matches=finished_matches,
            board=leaderboard(),
            user_points=sum(score_series_prediction(prediction)["total"] for prediction in user.series_predictions),
            score_details=score_details,
            score_series_prediction=score_series_prediction,
            series_predictions=SeriesPrediction.query.join(PlayoffSeries).order_by(PlayoffSeries.round_code).all(),
            round_weights=ROUND_WEIGHTS,
            round_labels=ROUND_LABELS,
        )

    @app.get("/bracket")
    def bracket():
        user = current_user()
        if not user:
            return redirect(url_for("login"))
        bracket_data = build_bracket_data()
        return render_template(
            "bracket.html",
            bracket=bracket_data,
            conference_labels=CONFERENCE_LABELS,
            round_labels=ROUND_LABELS,
            round_order=bracket_data["round_order"],
            round_rows=bracket_data["round_rows"],
        )

    @app.get("/admin")
    def admin_home():
        user = current_user()
        if not user or not user.is_admin:
            return redirect(url_for("cabinet"))
        return render_template("admin_home.html")

    @app.route("/admin/results", methods=["GET", "POST"])
    def admin_results():
        user = current_user()
        if not user:
            return redirect(url_for("login"))
        if not user.is_admin:
            flash("Доступ только для администраторов")
            return redirect(url_for("cabinet"))

        if request.method == "POST":
            action = request.form.get("action", "save_results")
            series_id = int(request.form["series_id"])
            series = PlayoffSeries.query.get_or_404(series_id)

            if action == "toggle_lock":
                game_index = int(request.form["game_index"])
                if game_index < 1 or game_index > 7:
                    flash("Некорректный номер матча")
                    return redirect(url_for("admin_results"))
                locked_games = parse_locked_games(series.locked_game_indices)
                if game_index in locked_games:
                    locked_games.remove(game_index)
                    flash(f"Матч {game_index}: блокировка снята")
                else:
                    locked_games.add(game_index)
                    flash(f"Матч {game_index}: прогноз заблокирован")
                series.locked_game_indices = serialize_locked_games(locked_games)
                db.session.commit()
                return redirect(url_for("admin_results"))

            wins_a = int(request.form["wins_a"])
            wins_b = int(request.form["wins_b"])
            if 4 not in (wins_a, wins_b):
                flash("Серия играется до 4 побед — одна из команд должна иметь 4")
                return redirect(url_for("admin_results"))
            if wins_a < 0 or wins_b < 0 or wins_a > 4 or wins_b > 4:
                flash("Некорректный счет серии")
                return redirect(url_for("admin_results"))

            games_count = wins_a + wins_b
            if games_count > 7:
                flash("В серии максимум 7 матчей")
                return redirect(url_for("admin_results"))

            raw_home_scores = request.form.getlist("game_home_scores")[:games_count]
            raw_away_scores = request.form.getlist("game_away_scores")[:games_count]
            if len(raw_home_scores) != games_count or len(raw_away_scores) != games_count:
                flash("Заполните точные счета всех сыгранных матчей")
                return redirect(url_for("admin_results"))

            scores: list[tuple[int, int]] = []
            outcomes: list[str] = []
            for idx, (raw_home, raw_away) in enumerate(zip(raw_home_scores, raw_away_scores), start=1):
                if not raw_home.isdigit() or not raw_away.isdigit():
                    flash(f"Матч {idx}: укажите счет неотрицательными числами")
                    return redirect(url_for("admin_results"))
                home_score = int(raw_home)
                away_score = int(raw_away)
                if home_score == away_score:
                    flash(f"Матч {idx}: в плей-офф не может быть ничьи")
                    return redirect(url_for("admin_results"))
                scores.append((home_score, away_score))
                outcomes.append("A" if home_score > away_score else "B")

            valid_sequence, message = validate_outcomes_sequence(outcomes, wins_a, wins_b)
            if not valid_sequence:
                flash(message)
                return redirect(url_for("admin_results"))

            Match.query.filter_by(series_id=series.id).delete()
            base_kickoff = datetime.now().replace(hour=19, minute=30, second=0, microsecond=0)
            for idx, (a_goals, b_goals) in enumerate(scores, start=1):
                home_team, away_team = game_teams_by_index(series, idx)
                if home_team == series.team_a:
                    home_score, away_score = a_goals, b_goals
                else:
                    home_score, away_score = b_goals, a_goals
                db.session.add(
                    Match(
                        home_team=home_team,
                        away_team=away_team,
                        kickoff=base_kickoff,
                        conference=series.conference,
                        round_code=series.round_code,
                        series_id=series.id,
                        home_score=home_score,
                        away_score=away_score,
                    )
                )
                base_kickoff = base_kickoff + timedelta(days=1)

            db.session.commit()
            flash("Результаты серии сохранены")
            return redirect(url_for("admin_results"))

        series_list = PlayoffSeries.query.order_by(PlayoffSeries.round_code, PlayoffSeries.conference, PlayoffSeries.id).all()
        results_by_series = {series.id: series_results_snapshot(series) for series in series_list}
        locked_games_by_series = {series.id: parse_locked_games(series.locked_game_indices) for series in series_list}
        return render_template(
            "admin_results.html",
            series_list=series_list,
            results_by_series=results_by_series,
            locked_games_by_series=locked_games_by_series,
            conference_labels=CONFERENCE_LABELS,
            round_labels=ROUND_LABELS,
        )

    @app.route("/admin/matches", methods=["GET", "POST"])
    def admin_matches():
        user = current_user()
        if not user:
            return redirect(url_for("login"))
        if not user.is_admin:
            flash("Доступ только для администраторов")
            return redirect(url_for("cabinet"))

        if request.method == "POST":
            action = request.form.get("action", "create_series")

            if action == "delete_series":
                series = PlayoffSeries.query.get_or_404(int(request.form["series_id"]))
                for match in series.matches:
                    Prediction.query.filter_by(match_id=match.id).delete()
                    db.session.delete(match)
                SeriesPrediction.query.filter_by(series_id=series.id).delete()
                db.session.delete(series)
                db.session.commit()
                flash("Серия удалена")
                return redirect(url_for("admin_matches"))

            team_a = request.form.get("team_a", "").strip()
            team_b = request.form.get("team_b", "").strip()
            conference = request.form.get("conference", "W")
            round_code = request.form.get("round_code", "R1")
            deadline_raw = request.form.get("prediction_deadline", "")
            if not team_a or not team_b or not deadline_raw:
                flash("Заполните команды и дедлайн")
                return redirect(url_for("admin_matches"))

            deadline = datetime.strptime(deadline_raw, "%Y-%m-%dT%H:%M")
            db.session.add(
                PlayoffSeries(
                    team_a=team_a,
                    team_b=team_b,
                    conference=conference,
                    round_code=round_code,
                    prediction_deadline=deadline,
                )
            )
            db.session.commit()
            flash("Серия добавлена")
            return redirect(url_for("admin_matches"))

        series_list = PlayoffSeries.query.order_by(PlayoffSeries.round_code, PlayoffSeries.id).all()
        return render_template(
            "admin_matches.html",
            series_list=series_list,
            conference_labels=CONFERENCE_LABELS,
            round_labels=ROUND_LABELS,
        )

    @app.route("/admin/users", methods=["GET", "POST"])
    def admin_users():
        user = current_user()
        if not user:
            return redirect(url_for("login"))
        if not user.is_admin:
            flash("Доступ только для администраторов")
            return redirect(url_for("cabinet"))

        if request.method == "POST":
            target = User.query.get_or_404(int(request.form["user_id"]))
            action = request.form.get("action")

            if target.is_admin:
                flash("Администраторов можно редактировать только вручную в БД")
                return redirect(url_for("admin_users"))
            if action == "block":
                target.is_blocked = True
                flash(f"Пользователь {target.username} заблокирован")
            elif action == "unblock":
                target.is_blocked = False
                flash(f"Пользователь {target.username} разблокирован")
            elif action == "delete":
                Prediction.query.filter_by(user_id=target.id).delete()
                SeriesPrediction.query.filter_by(user_id=target.id).delete()
                db.session.delete(target)
                flash("Пользователь удален")
            db.session.commit()
            return redirect(url_for("admin_users"))

        users = User.query.order_by(User.is_admin.desc(), User.display_name, User.username).all()
        return render_template("admin_users.html", users=users)


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
