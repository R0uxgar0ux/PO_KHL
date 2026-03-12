from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime
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


def ensure_schema_compatibility() -> None:
    inspector = db.inspect(db.engine)
    user_columns = {col["name"] for col in inspector.get_columns("user")}
    match_columns = {col["name"] for col in inspector.get_columns("match")}

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

    db.session.commit()

    for user in User.query.all():
        if not user.display_name:
            user.display_name = user.username
    db.session.commit()


def seed_matches() -> None:
    if Match.query.count() > 0 or PlayoffSeries.query.count() > 0:
        return

    s1 = PlayoffSeries(team_a="СКА", team_b="Локомотив", conference="W", round_code="R1")
    s2 = PlayoffSeries(team_a="Металлург", team_b="Авангард", conference="E", round_code="R1")
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
    match = prediction.match
    if not match.is_finished:
        return {"total": 0, "weight": ROUND_WEIGHTS.get(match.round_code, 1.0), "base": 0, "components": []}

    pred_home, pred_away = prediction.predicted_home, prediction.predicted_away
    real_home, real_away = match.home_score, match.away_score
    pred_diff, real_diff = pred_home - pred_away, real_home - real_away
    pred_total, real_total = pred_home + pred_away, real_home + real_away

    components: list[str] = []
    base_points = 0

    if _sign(pred_diff) == _sign(real_diff):
        base_points += 2
        components.append("угадан исход")
    if pred_diff == real_diff:
        base_points += 2
        components.append("угадана разница шайб")
    if pred_total == real_total:
        base_points += 1
        components.append("угадана сумма шайб")
    if pred_home == real_home and pred_away == real_away:
        base_points += 4
        components.append("точный счет")
    if pred_total >= 7 and real_total >= 7 and abs(pred_total - real_total) <= 1:
        base_points += 1
        components.append("бонус за высокий тотал")

    weight = ROUND_WEIGHTS.get(match.round_code, 1.0)
    return {"total": int(round(base_points * weight)), "weight": weight, "base": base_points, "components": components}


def score_prediction(prediction: Prediction) -> int:
    return score_details(prediction)["total"]


def leaderboard() -> list[dict]:
    result = []
    for user in User.query.order_by(User.display_name, User.username).all():
        points = sum(score_prediction(prediction) for prediction in user.predictions)
        exact_hits = sum(
            1
            for prediction in user.predictions
            if prediction.match.is_finished
            and prediction.predicted_home == prediction.match.home_score
            and prediction.predicted_away == prediction.match.away_score
        )
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


def register_routes(app: Flask) -> None:
    @app.context_processor
    def inject_user():
        return {"current_user": current_user()}

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
            favorite_team = request.form.get("favorite_team", user.favorite_team).strip() or "Авангард"
            bio = request.form.get("bio", user.bio).strip()

            if not is_valid_login(display_name):
                flash("Отображаемое имя должно быть 3-24 символа: латиница, цифры и _")
                return redirect(url_for("cabinet"))

            existing = User.query.filter(User.display_name == display_name, User.id != user.id).first()
            if existing:
                flash("Отображаемое имя уже занято")
                return redirect(url_for("cabinet"))

            user.display_name = display_name
            user.favorite_team = favorite_team
            user.bio = bio
            db.session.commit()
            flash("Профиль обновлен")
            return redirect(url_for("cabinet"))

        points = sum(score_prediction(prediction) for prediction in user.predictions)
        exact_hits = sum(
            1
            for prediction in user.predictions
            if prediction.match.is_finished
            and prediction.predicted_home == prediction.match.home_score
            and prediction.predicted_away == prediction.match.away_score
        )
        return render_template(
            "cabinet.html",
            points=points,
            rank=user_rank(user.id),
            total_users=User.query.count(),
            predictions_count=len(user.predictions),
            exact_hits=exact_hits,
        )

    @app.route("/predictions", methods=["GET", "POST"])
    def predictions():
        user = current_user()
        if not user:
            return redirect(url_for("login"))

        if request.method == "POST":
            match = Match.query.get_or_404(int(request.form["match_id"]))
            if match.is_finished:
                flash("Нельзя менять прогноз после окончания матча")
                return redirect(url_for("predictions"))

            predicted_home = int(request.form["predicted_home"])
            predicted_away = int(request.form["predicted_away"])
            prediction = Prediction.query.filter_by(user_id=user.id, match_id=match.id).first()
            if prediction:
                prediction.predicted_home = predicted_home
                prediction.predicted_away = predicted_away
                flash("Прогноз обновлен")
            else:
                db.session.add(Prediction(user_id=user.id, match_id=match.id, predicted_home=predicted_home, predicted_away=predicted_away))
                flash("Прогноз сохранен")
            db.session.commit()
            return redirect(url_for("predictions"))

        matches = Match.query.order_by(Match.kickoff).all()
        return render_template(
            "predictions.html",
            grouped_matches=group_matches_by_conference(matches),
            prediction_by_match={p.match_id: p for p in user.predictions},
            round_weights=ROUND_WEIGHTS,
            conference_labels=CONFERENCE_LABELS,
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
            user_points=sum(score_prediction(prediction) for prediction in user.predictions),
            score_details=score_details,
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
            match = Match.query.get_or_404(int(request.form["match_id"]))
            match.home_score = int(request.form["home_score"])
            match.away_score = int(request.form["away_score"])
            db.session.commit()
            flash("Результат сохранен")
            return redirect(url_for("admin_results"))

        matches = Match.query.order_by(Match.kickoff).all()
        return render_template("admin_results.html", matches=matches, conference_labels=CONFERENCE_LABELS)

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

            if action == "delete_match":
                match = Match.query.get_or_404(int(request.form["match_id"]))
                Prediction.query.filter_by(match_id=match.id).delete()
                db.session.delete(match)
                db.session.commit()
                flash("Матч удален")
                return redirect(url_for("admin_matches"))

            if action == "delete_series":
                series = PlayoffSeries.query.get_or_404(int(request.form["series_id"]))
                for match in series.matches:
                    Prediction.query.filter_by(match_id=match.id).delete()
                    db.session.delete(match)
                db.session.delete(series)
                db.session.commit()
                flash("Серия удалена")
                return redirect(url_for("admin_matches"))

            if action == "create_series":
                team_a = request.form.get("team_a", "").strip()
                team_b = request.form.get("team_b", "").strip()
                conference = request.form.get("conference", "W")
                round_code = request.form.get("round_code", "R1")
                if not team_a or not team_b:
                    flash("Заполните команды серии")
                    return redirect(url_for("admin_matches"))
                db.session.add(PlayoffSeries(team_a=team_a, team_b=team_b, conference=conference, round_code=round_code))
                db.session.commit()
                flash("Серия добавлена")
                return redirect(url_for("admin_matches"))

            if action == "add_game":
                series = PlayoffSeries.query.get_or_404(int(request.form["series_id"]))
                kickoff_raw = request.form.get("kickoff", "")
                host_side = request.form.get("host_side", "A")
                if not kickoff_raw:
                    flash("Укажите дату и время матча (МСК)")
                    return redirect(url_for("admin_matches"))

                kickoff = datetime.strptime(kickoff_raw, "%Y-%m-%dT%H:%M")
                home_team = series.team_a if host_side == "A" else series.team_b
                away_team = series.team_b if host_side == "A" else series.team_a
                db.session.add(
                    Match(
                        home_team=home_team,
                        away_team=away_team,
                        kickoff=kickoff,
                        conference=series.conference,
                        round_code=series.round_code,
                        series_id=series.id,
                    )
                )
                db.session.commit()
                flash("Матч в серии добавлен")
                return redirect(url_for("admin_matches"))

        series_list = PlayoffSeries.query.order_by(PlayoffSeries.round_code, PlayoffSeries.id).all()
        matches = Match.query.order_by(Match.kickoff).all()
        return render_template(
            "admin_matches.html",
            series_list=series_list,
            matches=matches,
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
                db.session.delete(target)
                flash("Пользователь удален")
            db.session.commit()
            return redirect(url_for("admin_users"))

        users = User.query.order_by(User.is_admin.desc(), User.display_name, User.username).all()
        return render_template("admin_users.html", users=users)


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
