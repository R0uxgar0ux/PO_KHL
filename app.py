from __future__ import annotations

import os
import re
import shutil
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Flask, flash, has_app_context, redirect, render_template, request, send_file, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "khl_playoff.db"))

db = SQLAlchemy()

ROUND_WEIGHTS = {"R1": 1.0, "QF": 1.0, "SF": 1.0, "F": 1.0}
SERIES_WINNER_POINTS = {"R1": 1, "QF": 2, "SF": 8, "F": 16}
SERIES_SCORE_POINTS = {"R1": 1, "QF": 2, "SF": 8, "F": 16}
MATCH_WINNER_POINTS = {"R1": 0, "QF": 0, "SF": 1, "F": 2}
MATCH_SCORE_POINTS = {"R1": 0, "QF": 0, "SF": 1, "F": 2}
ROUND_LABELS = {"R1": "1/8 финала", "QF": "1/4 финала", "SF": "1/2 финала", "F": "Финал"}
CONFERENCE_LABELS = {"W": "Запад", "E": "Восток"}
ROUND_SORT_PRIORITY = {"F": 0, "SF": 1, "QF": 2, "R1": 3}
LOGIN_RE = re.compile(r"^[a-zA-Z0-9_]{3,24}$")
DETAILED_ROUNDS = {"SF", "F"}
_RAW_SPORTS_DB_KEY = os.getenv("THESPORTSDB_API_KEY", "3")
THE_SPORTS_DB_API_KEY = "3" if _RAW_SPORTS_DB_KEY == "123" else _RAW_SPORTS_DB_KEY
THE_SPORTS_DB_BASE_URL = f"https://www.thesportsdb.com/api/v1/json/{THE_SPORTS_DB_API_KEY}"
LIVE_DATA_PROVIDER = (os.getenv("LIVE_DATA_PROVIDER", "thesportsdb") or "thesportsdb").strip().lower()
API_HOCKEY_BASE_URL = os.getenv("API_HOCKEY_BASE_URL", "https://v1.hockey.api-sports.io")
API_HOCKEY_KEY = os.getenv("API_HOCKEY_KEY", "")
API_HOCKEY_HOST = os.getenv("API_HOCKEY_HOST", "")
API_HOCKEY_KHL_LEAGUE_ID = os.getenv("API_HOCKEY_KHL_LEAGUE_ID", "57")
KHL_LEAGUE_ID = "4920"
LIVE_WINDOW_DAYS = 1
LIVE_CACHE_TTL_SECONDS = 120
_live_cache: dict[str, object] = {"timestamp": None, "payload": None}
LIVE_AUTO_SYNC_TTL_SECONDS = 300
_live_auto_sync_state: dict[str, object] = {"timestamp": None}
KHL_RU_TEAMS = {
    "avangard omsk": "Авангард",
    "lokomotiv yaroslavl": "Локомотив",
    "lokomotiv": "Локомотив",
    "yaroslavl": "Локомотив",
    "metallurg magnitogorsk": "Металлург",
    "metallurg": "Металлург",
    "magnitogorsk": "Металлург",
    "torpedo nizhny novgorod": "Торпедо",
    "torpedo": "Торпедо",
    "nizhny novgorod": "Торпедо",
    "dynamo moscow": "Динамо Москва",
    "dinamo moscow": "Динамо Москва",
    "dynamo moscow": "Динамо Москва",
    "dynamo minsk": "Динамо Минск",
    "dinamo minsk": "Динамо Минск",
    "salavat yulaev ufa": "Салават Юлаев",
    "salavat yulaev": "Салават Юлаев",
    "salavat ufa": "Салават Юлаев",
    "ak bars kazan": "Ак Барс",
    "ak bars": "Ак Барс",
    "bars kazan": "Ак Барс",
    "cska moscow": "ЦСКА",
    "ska saint petersburg": "СКА",
    "ska": "СКА",
    "spartak moscow": "Спартак",
    "spartak": "Спартак",
    "sibir novosibirsk": "Сибирь",
    "sibir": "Сибирь",
    "avtomobilist yekaterinburg": "Автомобилист",
    "avtomobilist": "Автомобилист",
    "neftekhimik nizhnekamsk": "Нефтехимик",
    "neftekhimik": "Нефтехимик",
    "severstal cherepovets": "Северсталь",
    "severstal": "Северсталь",
}
KHL_TEAM_MARKERS = (
    "avangard",
    "lokomotiv",
    "metallurg",
    "torpedo",
    "dynamo",
    "dinamo",
    "salavat",
    "ak bars",
    "cska",
    "ska",
    "spartak",
    "sibir",
    "avtomobilist",
    "neftekhimik",
    "severstal",
    "omsk",
    "yaroslavl",
    "magnitogorsk",
    "nizhny novgorod",
    "kazan",
    "nizhnekamsk",
    "cherepovets",
)

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

    maybe_backup_database_file(app)
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
    points_adjustment = db.Column(db.Integer, nullable=False, default=0)


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


class AppSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.String(500), nullable=False, default="")


class LiveEventStore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source_key = db.Column(db.String(200), unique=True, nullable=False)
    provider = db.Column(db.String(40), nullable=False, default="")
    home_team = db.Column(db.String(120), nullable=False, default="")
    away_team = db.Column(db.String(120), nullable=False, default="")
    event_datetime = db.Column(db.DateTime, nullable=False)
    home_score = db.Column(db.Integer)
    away_score = db.Column(db.Integer)
    is_finished = db.Column(db.Boolean, nullable=False, default=False)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    applied_at = db.Column(db.DateTime)


LIVE_SETTINGS_DEFAULTS = {
    "live_provider": LIVE_DATA_PROVIDER,
    "sportsdb_api_key": _RAW_SPORTS_DB_KEY,
    "api_hockey_base_url": API_HOCKEY_BASE_URL,
    "api_hockey_key": API_HOCKEY_KEY,
    "api_hockey_host": API_HOCKEY_HOST,
    "api_hockey_khl_league_id": API_HOCKEY_KHL_LEAGUE_ID,
}


def get_app_setting(key: str, default: str = "") -> str:
    if not has_app_context():
        return default
    setting = AppSetting.query.filter_by(key=key).first()
    if not setting:
        return default
    return setting.value


def set_app_setting(key: str, value: str) -> None:
    setting = AppSetting.query.filter_by(key=key).first()
    if setting:
        setting.value = value
    else:
        db.session.add(AppSetting(key=key, value=value))


def get_live_runtime_config() -> dict[str, str]:
    config: dict[str, str] = {}
    for key, default in LIVE_SETTINGS_DEFAULTS.items():
        config[key] = get_app_setting(key, str(default or ""))
    provider = (config.get("live_provider") or "thesportsdb").strip().lower()
    if provider not in {"thesportsdb", "api_hockey"}:
        provider = "thesportsdb"
    config["live_provider"] = provider
    return config


def _normalize_base_url(url: str, fallback: str) -> str:
    value = (url or "").strip()
    if not value:
        return fallback
    if value.startswith("http://"):
        return "https://" + value[len("http://"):]
    return value


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
    if "points_adjustment" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN points_adjustment INTEGER DEFAULT 0"))

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


def create_database_backup() -> Path | None:
    if DB_PATH == Path(":memory:") or not DB_PATH.exists():
        return None
    backup_dir = BASE_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"khl_playoff-{timestamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def maybe_backup_database_file(app: Flask) -> None:
    if app.config.get("TESTING"):
        return
    create_database_backup()


def sort_series_list(series_list: list[PlayoffSeries], conference_first: bool = False) -> list[PlayoffSeries]:
    conf_order = {"W": 0, "E": 1}
    if conference_first:
        return sorted(
            series_list,
            key=lambda s: (conf_order.get(s.conference, 99), ROUND_SORT_PRIORITY.get(s.round_code, 99), s.id),
        )
    return sorted(
        series_list,
        key=lambda s: (ROUND_SORT_PRIORITY.get(s.round_code, 99), conf_order.get(s.conference, 99), s.id),
    )


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
    round_code = series.round_code
    if not actual["finished"]:
        return {"total": 0, "base": 0, "weight": 1.0, "components": []}

    base = 0
    components: list[str] = []

    predicted_winner = "A" if prediction.predicted_wins_a > prediction.predicted_wins_b else "B"
    winner_correct = predicted_winner == actual["winner"]
    exact_series_score = prediction.predicted_wins_a == actual["wins_a"] and prediction.predicted_wins_b == actual["wins_b"]

    if winner_correct:
        points = SERIES_WINNER_POINTS.get(round_code, 0)
        base += points
        components.append(f"угадан победитель серии (+{points})")

    if exact_series_score:
        points = SERIES_SCORE_POINTS.get(round_code, 0)
        base += points
        components.append(f"точный счет серии (+{points})")

    predicted_scores = parse_game_scores(prediction.game_scores)
    match_winner_hits = 0
    exact_match_hits = 0
    for idx, real_score in enumerate(actual["scores"]):
        if idx >= len(predicted_scores):
            continue
        predicted_score = predicted_scores[idx]
        real_winner = "A" if real_score[0] > real_score[1] else "B"
        pred_winner = "A" if predicted_score[0] > predicted_score[1] else "B"

        if pred_winner == real_winner:
            points = MATCH_WINNER_POINTS.get(round_code, 0)
            base += points
            if points:
                match_winner_hits += 1

        if predicted_score == real_score:
            points = MATCH_SCORE_POINTS.get(round_code, 0)
            base += points
            if points:
                exact_match_hits += 1

    if match_winner_hits > 0:
        components.append(f"угадано победителей матчей: {match_winner_hits}")
    if exact_match_hits > 0:
        components.append(f"точных счетов матчей: {exact_match_hits}")

    return {"total": base, "base": base, "weight": 1.0, "components": components}


def user_total_points(user: User) -> int:
    raw_points = sum(score_series_prediction(prediction)["total"] for prediction in user.series_predictions)
    return raw_points + (user.points_adjustment or 0)


def leaderboard() -> list[dict]:
    result = []
    for user in User.query.order_by(User.display_name, User.username).all():
        points = user_total_points(user)
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


def build_results_insights(board: list[dict]) -> dict:
    total_players = len(board)
    leader = board[0] if board else None
    second = board[1] if len(board) > 1 else None

    avg_points = round(sum(row["points"] for row in board) / total_players, 2) if total_players else 0.0
    points_gap = (leader["points"] - second["points"]) if leader and second else 0
    top_points = leader["points"] if leader else 0
    top_leaders = [row["display_name"] for row in board if row["points"] == top_points] if leader else []

    stage_order = ["F", "SF", "QF", "R1"]
    users = User.query.all()
    stage_rows: list[dict] = []
    for stage_code in stage_order:
        finished_series = [s for s in PlayoffSeries.query.filter_by(round_code=stage_code).all() if series_actual(s)["finished"]]
        if not finished_series:
            continue

        leader_points = -1
        leader_names: list[str] = []
        exact_hits_max = 0
        for user in users:
            stage_points = 0
            stage_exact = 0
            for prediction in user.series_predictions:
                if prediction.series.round_code != stage_code:
                    continue
                stage_points += score_series_prediction(prediction)["total"]
                actual = series_actual(prediction.series)
                if actual["finished"] and prediction.predicted_wins_a == actual["wins_a"] and prediction.predicted_wins_b == actual["wins_b"]:
                    stage_exact += 1
            if stage_points > leader_points:
                leader_points = stage_points
                leader_names = [user.display_name]
            elif stage_points == leader_points:
                leader_names.append(user.display_name)
            exact_hits_max = max(exact_hits_max, stage_exact)

        stage_rows.append(
            {
                "round_code": stage_code,
                "round_label": ROUND_LABELS.get(stage_code, stage_code),
                "finished_series_count": len(finished_series),
                "leader_names": leader_names,
                "leader_points": leader_points,
                "max_exact_hits": exact_hits_max,
            }
        )

    return {
        "total_players": total_players,
        "leader": leader,
        "top_leaders": top_leaders,
        "top_points": top_points,
        "average_points": avg_points,
        "gap_to_second": points_gap,
        "stage_rows": stage_rows,
    }


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


def _sportsdb_get(path: str, params: dict[str, str], base_url: str) -> tuple[list[dict], bool, dict]:
    query = urlencode(params)
    url = f"{base_url.rstrip('/')}/{path}?{query}"
    try:
        with urlopen(url, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        events = payload.get("events") or []
        return events, True, {"url": url, "ok": True, "events_count": len(events), "error": ""}
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return [], False, {"url": url, "ok": False, "events_count": 0, "error": str(exc)}


def _apihockey_get(path: str, params: dict[str, str], base_url: str, api_key: str, api_host: str) -> tuple[list[dict], bool, dict]:
    query = urlencode(params)
    url = f"{base_url.rstrip('/')}/{path}?{query}"
    if not api_key:
        return [], False, {"url": url, "ok": False, "events_count": 0, "error": "API_HOCKEY_KEY is not configured"}

    headers = {"x-apisports-key": api_key}
    if api_host:
        headers["x-rapidapi-host"] = api_host

    try:
        request = Request(url, headers=headers)  # noqa: S310
        with urlopen(request, timeout=15) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        errors = payload.get("errors")
        if isinstance(errors, dict) and errors:
            error_text = "; ".join(f"{k}: {v}" for k, v in errors.items())
            return [], False, {"url": url, "ok": False, "events_count": 0, "error": error_text}
        events = payload.get("response") or []
        return events, True, {"url": url, "ok": True, "events_count": len(events), "error": ""}
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return [], False, {"url": url, "ok": False, "events_count": 0, "error": str(exc)}


def _sportsdb_events_day(date_value: str, base_url: str) -> tuple[list[dict], int]:
    events_by_league, ok_league, _ = _sportsdb_get("eventsday.php", {"d": date_value, "l": "Russian KHL"}, base_url)
    calls_ok = int(ok_league)
    if events_by_league:
        return events_by_league, calls_ok

    events_by_sport, ok_sport, _ = _sportsdb_get("eventsday.php", {"d": date_value, "s": "Hockey"}, base_url)
    calls_ok += int(ok_sport)
    return events_by_sport, calls_ok


def _provider_label(provider: str) -> str:
    if provider == "api_hockey":
        return "API-Hockey (paid)"
    return "TheSportsDB (free)"


def _normalize_team_name_ru(name: str | None) -> str:
    if not name:
        return "—"
    normalized = " ".join(re.sub(r"[^a-z0-9 ]+", " ", name.lower()).split())
    return KHL_RU_TEAMS.get(normalized, name)


def _is_khl_event(event: dict) -> bool:
    sport = (event.get("strSport") or "").lower()
    if "hockey" not in sport:
        return False

    league_id = str(event.get("idLeague") or "").strip()
    if league_id == KHL_LEAGUE_ID:
        return True

    league_name = (event.get("strLeague") or "").lower()
    if (
        "khl" in league_name
        or "континент" in league_name
        or "кхл" in league_name
        or "kontinental hockey league" in league_name
    ):
        return True

    home_team = (event.get("strHomeTeam") or "").lower()
    away_team = (event.get("strAwayTeam") or "").lower()
    teams_text = f"{home_team} {away_team}"
    return any(marker in teams_text for marker in KHL_TEAM_MARKERS)


def _is_khl_event_apihockey(event: dict, khl_league_id: str) -> bool:
    league = event.get("league") or {}
    sport = (league.get("sport") or "hockey").lower()
    if "hockey" not in sport:
        return False

    league_name = (league.get("name") or "").lower()
    if not league_name:
        return False

    excluded_markers = (
        "mhl",
        "vhl",
        "jhl",
        "u20",
        "u18",
        "junior",
        "women",
        "female",
        "вхл",
        "мхл",
        "жхл",
        "молод",
    )
    if any(marker in league_name for marker in excluded_markers):
        return False

    return "khl" in league_name or "kontinental hockey league" in league_name or "континентальная хоккейная лига" in league_name


def _parse_event_datetime_utc(event: dict) -> datetime | None:
    timestamp = event.get("strTimestamp")
    if timestamp:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(timestamp, pattern)
            except ValueError:
                continue

    date_event = event.get("dateEvent")
    time_event = event.get("strTime") or "00:00:00"
    if not date_event:
        return None
    if len(time_event) == 5:
        time_event = f"{time_event}:00"
    try:
        return datetime.strptime(f"{date_event} {time_event}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_apihockey_datetime_utc(event: dict) -> datetime | None:
    date_raw = event.get("date")
    if not date_raw:
        return None
    parsed = datetime.fromisoformat(str(date_raw).replace("Z", "+00:00"))
    if parsed.tzinfo:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _to_msk_label(dt_utc: datetime | None) -> tuple[str, str]:
    if not dt_utc:
        return "—", "—"
    dt_msk = dt_utc + timedelta(hours=3)
    return dt_msk.strftime("%d.%m"), dt_msk.strftime("%H:%M")


def _build_day_buckets(events: list[dict], dates: list[date]) -> list[dict]:
    by_day: dict[date, list[dict]] = {date_value: [] for date_value in dates}
    for event in events:
        dt_utc = event.get("datetime_utc")
        if not isinstance(dt_utc, datetime):
            continue
        date_msk = (dt_utc + timedelta(hours=3)).date()
        if date_msk in by_day:
            by_day[date_msk].append(event)

    buckets: list[dict] = []
    for date_value in dates:
        day_events = by_day.get(date_value, [])
        day_events.sort(key=lambda item: item.get("datetime_utc") or datetime.max)
        buckets.append({"date_label": date_value.strftime("%d.%m"), "events": day_events})
    return buckets


def _normalize_live_event(event: dict, now_utc: datetime, force_live: bool = False) -> dict:
    dt_utc = _parse_event_datetime_utc(event)
    date_label, time_label = _to_msk_label(dt_utc)
    home_score = event.get("intHomeScore")
    away_score = event.get("intAwayScore")
    status_raw = (event.get("strStatus") or "").strip()
    status_lower = status_raw.lower()
    is_live = force_live or any(token in status_lower for token in ("live", "progress", "in play", "ongoing"))

    if not is_live and dt_utc and home_score is not None and away_score is not None:
        is_live = dt_utc <= now_utc <= (dt_utc + timedelta(hours=4))

    is_finished = bool(home_score is not None and away_score is not None and not is_live)
    return {
        "id": event.get("idEvent"),
        "home_team": _normalize_team_name_ru(event.get("strHomeTeam")),
        "away_team": _normalize_team_name_ru(event.get("strAwayTeam")),
        "home_score": home_score,
        "away_score": away_score,
        "status": status_raw or ("LIVE" if is_live else ""),
        "datetime_utc": dt_utc,
        "date_label": date_label,
        "time_label": time_label,
        "is_live": is_live,
        "is_finished": is_finished,
    }


def _normalize_apihockey_event(event: dict, now_utc: datetime) -> dict:
    dt_utc = _parse_apihockey_datetime_utc(event)
    date_label, time_label = _to_msk_label(dt_utc)
    teams = event.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    scores = event.get("scores") or {}
    status = event.get("status") or {}
    status_long = (status.get("long") or "").strip()
    status_short = (status.get("short") or "").strip().upper()
    status_short_compact = status_short.replace(" ", "")
    elapsed = status.get("elapsed")
    has_period_marker = "P" in status_short_compact and any(ch.isdigit() for ch in status_short_compact)
    is_live = (
        status_short in {"1", "2", "3", "P", "LIVE", "INPLAY", "OT", "SO"}
        or has_period_marker
        or "live" in status_long.lower()
        or "period" in status_long.lower()
        or "in play" in status_long.lower()
        or (isinstance(elapsed, int) and elapsed > 0 and status_short not in {"FT", "AOT", "AP", "FINISHED"})
    )
    is_finished = status_short in {"FT", "AOT", "AP", "FINISHED"} or "finished" in status_long.lower()
    return {
        "id": event.get("id"),
        "home_team": _normalize_team_name_ru(home.get("name")),
        "away_team": _normalize_team_name_ru(away.get("name")),
        "home_score": scores.get("home"),
        "away_score": scores.get("away"),
        "status": status_long or status_short or ("LIVE" if is_live else ""),
        "datetime_utc": dt_utc,
        "date_label": date_label,
        "time_label": time_label,
        "is_live": is_live,
        "is_finished": is_finished and not is_live,
    }


def sync_live_results_to_series() -> dict[str, int]:
    groups = fetch_khl_live_groups(force_refresh=True, window_days=7)
    provider = str((groups.get("diagnostics") or {}).get("provider") or "unknown")
    events = list(groups.get("recent", [])) + list(groups.get("live", [])) + list(groups.get("upcoming", []))
    now_utc = datetime.utcnow()

    for event in events:
        dt_utc = event.get("datetime_utc")
        home_team = event.get("home_team")
        away_team = event.get("away_team")
        if not isinstance(dt_utc, datetime) or not isinstance(home_team, str) or not isinstance(away_team, str):
            continue
        event_id = str(event.get("id") or f"{dt_utc.isoformat()}:{home_team}:{away_team}")
        source_key = f"{provider}:{event_id}"
        stored = LiveEventStore.query.filter_by(source_key=source_key).first()
        if stored is None:
            stored = LiveEventStore(source_key=source_key)
            db.session.add(stored)
        stored.provider = provider
        stored.home_team = home_team
        stored.away_team = away_team
        stored.event_datetime = dt_utc
        stored.home_score = event.get("home_score")
        stored.away_score = event.get("away_score")
        stored.is_finished = bool(event.get("is_finished"))
        stored.last_seen_at = now_utc

    records = (
        LiveEventStore.query.filter_by(is_finished=True)
        .order_by(LiveEventStore.event_datetime.asc(), LiveEventStore.id.asc())
        .all()
    )
    series_list = PlayoffSeries.query.all()
    series_by_teams: dict[frozenset[str], list[PlayoffSeries]] = defaultdict(list)
    for series in series_list:
        series_by_teams[frozenset((series.team_a, series.team_b))].append(series)

    created = 0
    updated = 0
    unchanged = 0
    skipped = 0

    for record in records:
        home_team = record.home_team
        away_team = record.away_team
        home_score = record.home_score
        away_score = record.away_score
        if not home_team or not away_team:
            skipped += 1
            continue
        if not isinstance(home_score, int) or not isinstance(away_score, int):
            skipped += 1
            continue

        event_dt = record.event_datetime
        if not isinstance(event_dt, datetime):
            event_dt = now_utc

        candidates = series_by_teams.get(frozenset((home_team, away_team)), [])
        if not candidates:
            skipped += 1
            continue

        def _candidate_rank(item: PlayoffSeries) -> tuple[int, int, int]:
            has_same_day = any(match.kickoff.date() == event_dt.date() for match in item.matches)
            has_same_pair = any(match.home_team == home_team and match.away_team == away_team for match in item.matches)
            return (
                0 if has_same_day else 1,
                0 if has_same_pair else 1,
                -item.id,
            )

        series = sorted(candidates, key=_candidate_rank)[0]

        matching_matches = sorted(
            [m for m in series.matches if m.home_team == home_team and m.away_team == away_team],
            key=lambda m: m.kickoff,
        )
        match = next((m for m in matching_matches if m.kickoff.date() == event_dt.date()), None)
        if match is None:
            match = next((m for m in matching_matches if not m.is_finished), None)

        if match is None:
            db.session.add(
                Match(
                    home_team=home_team,
                    away_team=away_team,
                    kickoff=event_dt,
                    conference=series.conference,
                    round_code=series.round_code,
                    series_id=series.id,
                    home_score=home_score,
                    away_score=away_score,
                )
            )
            record.applied_at = now_utc
            created += 1
            continue

        if match.home_score == home_score and match.away_score == away_score:
            if record.applied_at is None:
                record.applied_at = now_utc
            unchanged += 1
            continue
        match.home_score = home_score
        match.away_score = away_score
        record.applied_at = now_utc
        updated += 1

    db.session.commit()
    return {"created": created, "updated": updated, "unchanged": unchanged, "skipped": skipped}


def auto_sync_live_results_if_needed() -> dict[str, int] | None:
    now_utc = datetime.utcnow()
    last_synced = _live_auto_sync_state.get("timestamp")
    if isinstance(last_synced, datetime):
        if (now_utc - last_synced).total_seconds() < LIVE_AUTO_SYNC_TTL_SECONDS:
            return None
    stats = sync_live_results_to_series()
    _live_auto_sync_state["timestamp"] = now_utc
    return stats


def fetch_khl_live_groups(
    now_utc: datetime | None = None,
    force_refresh: bool = False,
    window_days: int | None = None,
) -> dict[str, list[dict]]:
    now_utc = now_utc or datetime.utcnow()
    live_config = get_live_runtime_config()
    provider = live_config["live_provider"]
    sportsdb_key_raw = live_config.get("sportsdb_api_key") or "3"
    sportsdb_api_key = "3" if sportsdb_key_raw == "123" else sportsdb_key_raw
    sportsdb_base_url = _normalize_base_url(
        f"https://www.thesportsdb.com/api/v1/json/{sportsdb_api_key}",
        THE_SPORTS_DB_BASE_URL,
    )
    api_hockey_base_url = _normalize_base_url(
        live_config.get("api_hockey_base_url") or API_HOCKEY_BASE_URL,
        API_HOCKEY_BASE_URL,
    )
    api_hockey_key = live_config.get("api_hockey_key") or ""
    api_hockey_host = live_config.get("api_hockey_host") or ""
    api_hockey_khl_league_id = live_config.get("api_hockey_khl_league_id") or API_HOCKEY_KHL_LEAGUE_ID

    effective_window_days = max(1, int(window_days or LIVE_WINDOW_DAYS))

    cached_at = _live_cache.get("timestamp")
    cached_payload = _live_cache.get("payload")
    if (
        not force_refresh
        and window_days is None
        and isinstance(cached_at, datetime)
        and isinstance(cached_payload, dict)
    ):
        cached_provider = str((cached_payload.get("diagnostics") or {}).get("provider") or "")
        if cached_provider == provider and (now_utc - cached_at).total_seconds() <= LIVE_CACHE_TTL_SECONDS:
            payload = dict(cached_payload)
            diagnostics = dict(payload.get("diagnostics", {}))
            diagnostics["cache_hit"] = True
            diagnostics["cache_age_sec"] = int((now_utc - cached_at).total_seconds())
            payload["diagnostics"] = diagnostics
            return payload  # type: ignore[return-value]

    upcoming: list[dict] = []
    live: list[dict] = []
    recent: list[dict] = []
    window = timedelta(days=effective_window_days)

    successful_calls = 0
    diagnostics_calls: list[dict] = []
    all_events: list[dict] = []

    if provider == "api_hockey":
        start_date = (now_utc - window).date()
        end_date = (now_utc + window).date()
        current = start_date
        seen_ids: set[str] = set()
        while current <= end_date:
            day_events, ok_day, trace_day = _apihockey_get(
                "games",
                {"date": current.isoformat(), "league": api_hockey_khl_league_id, "season": str(current.year)},
                api_hockey_base_url,
                api_hockey_key,
                api_hockey_host,
            )
            diagnostics_calls.append(trace_day)
            successful_calls += int(ok_day)
            if not day_events:
                day_events_no_league, ok_no_league, trace_no_league = _apihockey_get(
                    "games",
                    {"date": current.isoformat()},
                    api_hockey_base_url,
                    api_hockey_key,
                    api_hockey_host,
                )
                diagnostics_calls.append(trace_no_league)
                successful_calls += int(ok_no_league)
                day_events = day_events_no_league
            for raw_event in day_events:
                if not _is_khl_event_apihockey(raw_event, api_hockey_khl_league_id):
                    continue
                event_id = str(raw_event.get("id") or "")
                if event_id and event_id in seen_ids:
                    continue
                if event_id:
                    seen_ids.add(event_id)
                all_events.append(_normalize_apihockey_event(raw_event, now_utc))
            current += timedelta(days=1)
    else:
        all_by_day: list[tuple[dict, bool]] = []
        start_date = (now_utc - window).date()
        end_date = (now_utc + window).date()
        current = start_date
        while current <= end_date:
            day_events_league, ok_league, trace_league = _sportsdb_get(
                "eventsday.php",
                {"d": current.isoformat(), "l": "Russian KHL"},
                sportsdb_base_url,
            )
            diagnostics_calls.append(trace_league)
            successful_calls += int(ok_league)
            day_events = [(item, True) for item in day_events_league]
            if not day_events_league:
                day_events_sport, ok_sport, trace_sport = _sportsdb_get(
                    "eventsday.php",
                    {"d": current.isoformat(), "s": "Hockey"},
                    sportsdb_base_url,
                )
                diagnostics_calls.append(trace_sport)
                successful_calls += int(ok_sport)
                day_events = [(item, False) for item in day_events_sport]
            all_by_day.extend(day_events)
            current += timedelta(days=1)

        # Fallback для случаев, когда daily endpoint отдал пусто.
        if not all_by_day:
            next_events, ok_next, trace_next = _sportsdb_get("eventsnextleague.php", {"id": KHL_LEAGUE_ID}, sportsdb_base_url)
            past_events, ok_past, trace_past = _sportsdb_get("eventspastleague.php", {"id": KHL_LEAGUE_ID}, sportsdb_base_url)
            diagnostics_calls.extend([trace_next, trace_past])
            successful_calls += int(ok_next) + int(ok_past)
            all_by_day.extend((item, True) for item in next_events)
            all_by_day.extend((item, True) for item in past_events)

        seen_ids: set[str] = set()
        for raw_event, _trusted_khl in all_by_day:
            if not _is_khl_event(raw_event):
                continue
            event_id = str(raw_event.get("idEvent") or "")
            if event_id and event_id in seen_ids:
                continue
            if event_id:
                seen_ids.add(event_id)
            all_events.append(_normalize_live_event(raw_event, now_utc))

        if not all_events:
            next_events, ok_next, trace_next = _sportsdb_get("eventsnextleague.php", {"id": KHL_LEAGUE_ID}, sportsdb_base_url)
            past_events, ok_past, trace_past = _sportsdb_get("eventspastleague.php", {"id": KHL_LEAGUE_ID}, sportsdb_base_url)
            diagnostics_calls.extend([trace_next, trace_past])
            successful_calls += int(ok_next) + int(ok_past)
            for raw_event in next_events + past_events:
                event_id = str(raw_event.get("idEvent") or "")
                if event_id and event_id in seen_ids:
                    continue
                if event_id:
                    seen_ids.add(event_id)
                all_events.append(_normalize_live_event(raw_event, now_utc))

    existing_signatures = {
        (
            str(event.get("datetime_utc") or ""),
            str(event.get("home_team") or ""),
            str(event.get("away_team") or ""),
        )
        for event in all_events
    }
    if has_app_context():
        stored_start = now_utc - window
        stored_end = now_utc + window
        stored_events = (
            LiveEventStore.query.filter(
                LiveEventStore.provider == provider,
                LiveEventStore.event_datetime >= stored_start,
                LiveEventStore.event_datetime <= stored_end,
            )
            .order_by(LiveEventStore.event_datetime.asc())
            .all()
        )
        for record in stored_events:
            signature = (str(record.event_datetime), record.home_team, record.away_team)
            if signature in existing_signatures:
                continue
            date_label, time_label = _to_msk_label(record.event_datetime)
            all_events.append(
                {
                    "id": record.source_key,
                    "home_team": record.home_team,
                    "away_team": record.away_team,
                    "home_score": record.home_score,
                    "away_score": record.away_score,
                    "status": "FINISHED" if record.is_finished else "",
                    "datetime_utc": record.event_datetime,
                    "date_label": date_label,
                    "time_label": time_label,
                    "is_live": False,
                    "is_finished": bool(record.is_finished),
                }
            )

    for event in all_events:
        dt = event["datetime_utc"]
        if event["is_live"]:
            live.append(event)
            continue
        if not dt:
            continue
        if now_utc <= dt <= now_utc + window:
            upcoming.append(event)
            continue
        if now_utc - window <= dt < now_utc:
            recent.append(event)

    upcoming.sort(key=lambda item: item["datetime_utc"] or datetime.max)
    live.sort(key=lambda item: item["datetime_utc"] or datetime.max)
    recent.sort(key=lambda item: item["datetime_utc"] or datetime.min, reverse=True)

    today_msk = (now_utc + timedelta(hours=3)).date()
    upcoming_dates = [today_msk + timedelta(days=offset) for offset in range(0, effective_window_days + 1)]
    recent_dates = [today_msk - timedelta(days=offset) for offset in range(1, effective_window_days + 1)]
    upcoming_day_buckets = _build_day_buckets(upcoming, upcoming_dates)
    recent_day_buckets = _build_day_buckets(recent, recent_dates)

    error_message = ""
    source_label = _provider_label(provider)
    if successful_calls == 0:
        if isinstance(cached_payload, dict):
            return cached_payload  # type: ignore[return-value]
        error_message = f"Не удалось загрузить live-данные из {source_label}"

    diagnostics = {
        "provider": provider,
        "source_label": source_label,
        "cache_hit": False,
        "cache_age_sec": 0,
        "successful_calls": successful_calls,
        "raw_events_total": sum(int(call.get("events_count", 0)) for call in diagnostics_calls),
        "filtered_events_total": len(all_events),
        "calls": diagnostics_calls,
    }
    payload = {
        "upcoming": upcoming,
        "live": live,
        "recent": recent,
        "upcoming_days": upcoming_day_buckets,
        "recent_days": recent_day_buckets,
        "error": error_message,
        "diagnostics": diagnostics,
        "source_label": source_label,
    }
    if window_days is None:
        _live_cache["timestamp"] = now_utc
        _live_cache["payload"] = payload
    return payload

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

        points = user_total_points(user)
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

        series_list = sort_series_list(PlayoffSeries.query.all())
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

    @app.get("/live")
    def live():
        user = current_user()
        if not user:
            return redirect(url_for("login"))
        auto_sync_live_results_if_needed()
        force_refresh = request.args.get("nocache") == "1"
        groups = fetch_khl_live_groups(force_refresh=force_refresh)
        if groups["error"]:
            flash(groups["error"])
        return render_template(
            "live.html",
            upcoming_events=groups["upcoming"],
            upcoming_days=groups.get("upcoming_days", []),
            live_events=groups["live"],
            past_events=groups["recent"],
            past_days=groups.get("recent_days", []),
            diagnostics=groups.get("diagnostics", {}),
            source_label=groups.get("source_label", _provider_label(get_live_runtime_config()["live_provider"])),
            live_window_days=LIVE_WINDOW_DAYS,
        )

    @app.get("/results")
    def results():
        user = current_user()
        if not user:
            return redirect(url_for("login"))
        board = leaderboard()
        finished_matches = Match.query.filter(Match.home_score.isnot(None)).order_by(Match.kickoff).all()
        return render_template(
            "results.html",
            finished_matches=finished_matches,
            board=board,
            user_points=user_total_points(user),
            score_details=score_details,
            score_series_prediction=score_series_prediction,
            round_labels=ROUND_LABELS,
            insights=build_results_insights(board),
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


    @app.get("/regulations")
    def regulations():
        user = current_user()
        if not user:
            return redirect(url_for("login"))
        return render_template("regulations.html")

    @app.get("/admin")
    def admin_home():
        user = current_user()
        if not user or not user.is_admin:
            return redirect(url_for("cabinet"))
        return render_template("admin_home.html")

    @app.post("/admin/backup")
    def admin_backup():
        user = current_user()
        if not user:
            return redirect(url_for("login"))
        if not user.is_admin:
            flash("Доступ только для администраторов")
            return redirect(url_for("cabinet"))
        backup_path = create_database_backup()
        if not backup_path:
            flash("Не удалось создать бэкап базы")
            return redirect(url_for("admin_home"))
        return send_file(backup_path, as_attachment=True, download_name=backup_path.name)

    @app.route("/admin/live-settings", methods=["GET", "POST"])
    def admin_live_settings():
        user = current_user()
        if not user:
            return redirect(url_for("login"))
        if not user.is_admin:
            flash("Доступ только для администраторов")
            return redirect(url_for("cabinet"))

        if request.method == "POST":
            provider = (request.form.get("live_provider", "thesportsdb") or "thesportsdb").strip().lower()
            if provider not in {"thesportsdb", "api_hockey"}:
                provider = "thesportsdb"

            set_app_setting("live_provider", provider)
            set_app_setting("sportsdb_api_key", (request.form.get("sportsdb_api_key", "") or "").strip())
            set_app_setting("api_hockey_key", (request.form.get("api_hockey_key", "") or "").strip())
            set_app_setting("api_hockey_base_url", (request.form.get("api_hockey_base_url", "") or "").strip())
            set_app_setting("api_hockey_host", (request.form.get("api_hockey_host", "") or "").strip())
            set_app_setting("api_hockey_khl_league_id", (request.form.get("api_hockey_khl_league_id", "") or "").strip())
            db.session.commit()

            _live_cache["timestamp"] = None
            _live_cache["payload"] = None
            _live_auto_sync_state["timestamp"] = None
            flash("LIVE API настройки сохранены")
            return redirect(url_for("admin_live_settings"))

        current_config = get_live_runtime_config()
        return render_template("admin_live_settings.html", settings=current_config)

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
            if action == "sync_live":
                stats = sync_live_results_to_series()
                flash(
                    "Импорт из LIVE выполнен: "
                    f"создано {stats['created']}, обновлено {stats['updated']}, "
                    f"без изменений {stats['unchanged']}, пропущено {stats['skipped']}"
                )
                return redirect(url_for("admin_results"))

            series_id = int(request.form["series_id"])
            series = PlayoffSeries.query.get_or_404(series_id)
            focus_url = f"{url_for('admin_results')}#series-{series.id}"

            if action == "toggle_lock":
                game_index = int(request.form["game_index"])
                if game_index < 1 or game_index > 7:
                    flash("Некорректный номер матча")
                    return redirect(focus_url)
                locked_games = parse_locked_games(series.locked_game_indices)
                if game_index in locked_games:
                    locked_games.remove(game_index)
                    flash(f"Матч {game_index}: блокировка снята")
                else:
                    locked_games.add(game_index)
                    flash(f"Матч {game_index}: прогноз заблокирован")
                series.locked_game_indices = serialize_locked_games(locked_games)
                db.session.commit()
                return redirect(focus_url)

            wins_a = int(request.form["wins_a"])
            wins_b = int(request.form["wins_b"])
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

            raw_home_scores = request.form.getlist("game_home_scores")[:games_count]
            raw_away_scores = request.form.getlist("game_away_scores")[:games_count]
            if len(raw_home_scores) != games_count or len(raw_away_scores) != games_count:
                flash("Заполните точные счета всех сыгранных матчей")
                return redirect(focus_url)

            outcomes: list[str] = []
            matches_to_save: list[tuple[str, str, int, int]] = []
            for idx, (raw_home, raw_away) in enumerate(zip(raw_home_scores, raw_away_scores), start=1):
                if not raw_home.isdigit() or not raw_away.isdigit():
                    flash(f"Матч {idx}: укажите счет неотрицательными числами")
                    return redirect(focus_url)
                home_score = int(raw_home)
                away_score = int(raw_away)
                if home_score == away_score:
                    flash(f"Матч {idx}: в плей-офф не может быть ничьи")
                    return redirect(focus_url)

                home_team, away_team = game_teams_by_index(series, idx)
                if home_team == series.team_a:
                    a_goals, b_goals = home_score, away_score
                else:
                    a_goals, b_goals = away_score, home_score

                outcomes.append("A" if a_goals > b_goals else "B")
                matches_to_save.append((home_team, away_team, home_score, away_score))

            valid_sequence, message = validate_outcomes_sequence(outcomes, wins_a, wins_b)
            if not valid_sequence:
                flash(message)
                return redirect(focus_url)

            Match.query.filter_by(series_id=series.id).delete()
            base_kickoff = datetime.now().replace(hour=19, minute=30, second=0, microsecond=0)
            for home_team, away_team, home_score, away_score in matches_to_save:
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
            return redirect(focus_url)

        auto_stats = auto_sync_live_results_if_needed()
        if auto_stats and (auto_stats["created"] > 0 or auto_stats["updated"] > 0):
            flash(
                "Автосинхронизация LIVE: "
                f"создано {auto_stats['created']}, обновлено {auto_stats['updated']}"
            )

        series_list = sort_series_list(PlayoffSeries.query.all())
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
            if team_a == team_b:
                flash("Команды серии должны быть разными")
                return redirect(url_for("admin_matches"))
            duplicate = PlayoffSeries.query.filter_by(
                team_a=team_a,
                team_b=team_b,
                conference=conference,
                round_code=round_code,
            ).first()
            if duplicate:
                flash("Такая серия уже существует")
                return redirect(url_for("admin_matches"))

            deadline = datetime.strptime(deadline_raw, "%Y-%m-%dT%H:%M")
            if deadline < datetime.now():
                flash("Дедлайн не может быть в прошлом")
                return redirect(url_for("admin_matches"))
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

        series_list = sort_series_list(PlayoffSeries.query.all())
        return render_template(
            "admin_matches.html",
            series_list=series_list,
            conference_labels=CONFERENCE_LABELS,
            round_labels=ROUND_LABELS,
        )

    @app.route("/admin/predictions", methods=["GET", "POST"])
    def admin_predictions():
        user = current_user()
        if not user:
            return redirect(url_for("login"))
        if not user.is_admin:
            flash("Доступ только для администраторов")
            return redirect(url_for("cabinet"))

        if request.method == "POST":
            action = request.form.get("action", "")
            if action == "save_prediction":
                target_user_id_raw = request.form.get("user_id", "")
                target_series_id_raw = request.form.get("series_id", "")
                score_raw = request.form.get("series_score", "")
                anchor_raw = request.form.get("anchor", "").strip()
                anchor = anchor_raw if re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", anchor_raw) else ""
                try:
                    target_user_id = int(target_user_id_raw)
                    target_series_id = int(target_series_id_raw)
                except ValueError:
                    flash("Некорректный пользователь или серия")
                    return redirect(url_for("admin_predictions"))

                if ":" not in score_raw:
                    flash("Некорректный формат счета серии")
                    return redirect(url_for("admin_predictions"))
                left_raw, right_raw = score_raw.split(":", 1)
                if not left_raw.isdigit() or not right_raw.isdigit():
                    flash("Счет серии должен содержать только числа")
                    return redirect(url_for("admin_predictions"))

                wins_a = int(left_raw)
                wins_b = int(right_raw)
                if 4 not in (wins_a, wins_b) or min(wins_a, wins_b) < 0 or max(wins_a, wins_b) > 4:
                    flash("Допустимы только счета формата 4:x или x:4 (где x = 0..3)")
                    return redirect(url_for("admin_predictions"))

                target_user = User.query.get_or_404(target_user_id)
                target_series = PlayoffSeries.query.get_or_404(target_series_id)
                prediction = SeriesPrediction.query.filter_by(user_id=target_user.id, series_id=target_series.id).first()
                if prediction:
                    prediction.predicted_wins_a = wins_a
                    prediction.predicted_wins_b = wins_b
                    prediction.game_outcomes = ""
                    prediction.game_scores = ""
                    flash(f"Прогноз для {target_user.username} обновлен")
                else:
                    db.session.add(
                        SeriesPrediction(
                            user_id=target_user.id,
                            series_id=target_series.id,
                            predicted_wins_a=wins_a,
                            predicted_wins_b=wins_b,
                            game_outcomes="",
                            game_scores="",
                        )
                    )
                    flash(f"Прогноз для {target_user.username} сохранен")
                db.session.commit()
                destination = url_for("admin_predictions")
                if anchor:
                    destination = f"{destination}#{anchor}"
                return redirect(destination)

        users = User.query.order_by(User.display_name, User.username).all()
        series_list = sort_series_list(PlayoffSeries.query.all())

        rows: list[dict] = []
        for u in users:
            predictions_by_series = {p.series_id: p for p in u.series_predictions}
            user_rows = []
            raw_points = 0
            for series in series_list:
                p = predictions_by_series.get(series.id)
                if p:
                    details = score_series_prediction(p)
                    raw_points += details["total"]
                    user_rows.append({
                        "series": series,
                        "prediction": p,
                        "points": details["total"],
                        "has_prediction": True,
                    })
                else:
                    user_rows.append({
                        "series": series,
                        "prediction": None,
                        "points": 0,
                        "has_prediction": False,
                    })

            stage_points = {"R1": 0, "QF": 0, "SF": 0, "F": 0}
            missing_count = 0
            for row in user_rows:
                if row["has_prediction"]:
                    stage_points[row["series"].round_code] = stage_points.get(row["series"].round_code, 0) + row["points"]
                else:
                    missing_count += 1

            rows.append({
                "user": u,
                "rows": user_rows,
                "raw_points": raw_points,
                "adjustment": u.points_adjustment or 0,
                "total_points": raw_points + (u.points_adjustment or 0),
                "stage_points": stage_points,
                "missing_count": missing_count,
            })

        return render_template("admin_predictions.html", users_rows=rows)

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
            elif action == "set_adjustment":
                try:
                    adjustment = int(request.form.get("points_adjustment", "0"))
                except ValueError:
                    flash("Корректировка очков должна быть целым числом")
                    return redirect(url_for("admin_users"))
                target.points_adjustment = adjustment
                flash(f"Корректировка очков для {target.username} установлена: {adjustment}")
            elif action == "recalculate":
                recalculated_raw = sum(score_series_prediction(prediction)["total"] for prediction in target.series_predictions)
                recalculated_total = recalculated_raw + (target.points_adjustment or 0)
                flash(
                    f"Пересчет выполнен для {target.username}: авто {recalculated_raw}, "
                    f"коррекция {target.points_adjustment or 0}, итог {recalculated_total}"
                )
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
