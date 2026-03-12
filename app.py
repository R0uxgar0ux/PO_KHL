from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os

from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "khl_playoff.db"))

db = SQLAlchemy()

ROUND_WEIGHTS = {
    "R1": 1.0,  # 1/8 финала
    "QF": 1.25,  # 1/4 финала
    "SF": 1.6,  # 1/2 финала
    "F": 2.2,  # Финал
}

ROUND_LABELS = {
    "R1": "1/8 финала",
    "QF": "1/4 финала",
    "SF": "1/2 финала",
    "F": "Финал",
}


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
        seed_matches()

    register_routes(app)
    return app


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)


class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    home_team = db.Column(db.String(120), nullable=False)
    away_team = db.Column(db.String(120), nullable=False)
    kickoff = db.Column(db.DateTime, nullable=False)
    round_code = db.Column(db.String(8), nullable=False, default="R1")
    home_score = db.Column(db.Integer)
    away_score = db.Column(db.Integer)

    @property
    def is_finished(self) -> bool:
        return self.home_score is not None and self.away_score is not None

    @property
    def round_label(self) -> str:
        return ROUND_LABELS.get(self.round_code, self.round_code)


class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=False)
    predicted_home = db.Column(db.Integer, nullable=False)
    predicted_away = db.Column(db.Integer, nullable=False)

    user = db.relationship("User", backref=db.backref("predictions", lazy=True))
    match = db.relationship("Match", backref=db.backref("predictions", lazy=True))

    __table_args__ = (db.UniqueConstraint("user_id", "match_id", name="uq_user_match"),)


def seed_matches() -> None:
    if Match.query.count() > 0:
        return

    matches = [
        Match(home_team="СКА", away_team="Локомотив", kickoff=datetime(2026, 3, 15, 19, 30), round_code="R1"),
        Match(home_team="Металлург", away_team="Авангард", kickoff=datetime(2026, 3, 16, 17, 0), round_code="QF"),
        Match(home_team="Ак Барс", away_team="Салават Юлаев", kickoff=datetime(2026, 3, 16, 19, 30), round_code="SF"),
        Match(home_team="ЦСКА", away_team="Трактор", kickoff=datetime(2026, 4, 5, 19, 0), round_code="F"),
    ]
    db.session.add_all(matches)
    db.session.commit()


def current_user() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def _sign(value: int) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def score_details(prediction: Prediction) -> dict:
    match = prediction.match
    if not match.is_finished:
        return {
            "total": 0,
            "weight": ROUND_WEIGHTS.get(match.round_code, 1.0),
            "base": 0,
            "components": [],
        }

    pred_home, pred_away = prediction.predicted_home, prediction.predicted_away
    real_home, real_away = match.home_score, match.away_score

    pred_diff = pred_home - pred_away
    real_diff = real_home - real_away
    pred_total = pred_home + pred_away
    real_total = real_home + real_away

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

    exact_score = pred_home == real_home and pred_away == real_away
    if exact_score:
        base_points += 4
        components.append("точный счет")

    # Риск-бонус: за смелые ставки с 7+ шайб при совпавшем тренде по тоталу
    if pred_total >= 7 and real_total >= 7 and abs(pred_total - real_total) <= 1:
        base_points += 1
        components.append("бонус за высокий тотал")

    weight = ROUND_WEIGHTS.get(match.round_code, 1.0)
    total = int(round(base_points * weight))

    return {
        "total": total,
        "weight": weight,
        "base": base_points,
        "components": components,
    }


def score_prediction(prediction: Prediction) -> int:
    return score_details(prediction)["total"]


def leaderboard() -> list[dict]:
    result = []
    for user in User.query.order_by(User.username).all():
        predictions = user.predictions
        points = sum(score_prediction(prediction) for prediction in predictions)
        exact_hits = 0
        for prediction in predictions:
            match = prediction.match
            if match.is_finished and prediction.predicted_home == match.home_score and prediction.predicted_away == match.away_score:
                exact_hits += 1

        result.append({"username": user.username, "points": points, "exact_hits": exact_hits})

    return sorted(result, key=lambda item: (item["points"], item["exact_hits"], item["username"]), reverse=True)


def register_routes(app: Flask) -> None:
    @app.context_processor
    def inject_user():
        return {"current_user": current_user()}

    @app.get("/")
    def index():
        if not current_user():
            return redirect(url_for("login"))
        return redirect(url_for("cabinet"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            if not username or not password:
                flash("Введите логин и пароль")
                return redirect(url_for("register"))

            if User.query.filter_by(username=username).first():
                flash("Такой пользователь уже существует")
                return redirect(url_for("register"))

            user = User(username=username, password_hash=generate_password_hash(password))
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
            match_id = int(request.form["match_id"])
            predicted_home = int(request.form["predicted_home"])
            predicted_away = int(request.form["predicted_away"])

            match = Match.query.get_or_404(match_id)
            if match.is_finished:
                flash("Нельзя менять прогноз после окончания матча")
                return redirect(url_for("cabinet"))

            prediction = Prediction.query.filter_by(user_id=user.id, match_id=match_id).first()
            if prediction:
                prediction.predicted_home = predicted_home
                prediction.predicted_away = predicted_away
                flash("Прогноз обновлен")
            else:
                prediction = Prediction(
                    user_id=user.id,
                    match_id=match_id,
                    predicted_home=predicted_home,
                    predicted_away=predicted_away,
                )
                db.session.add(prediction)
                flash("Прогноз сохранен")

            db.session.commit()
            return redirect(url_for("cabinet"))

        matches = Match.query.order_by(Match.kickoff).all()
        prediction_by_match = {p.match_id: p for p in user.predictions}
        return render_template(
            "cabinet.html",
            matches=matches,
            prediction_by_match=prediction_by_match,
            round_weights=ROUND_WEIGHTS,
        )

    @app.get("/results")
    def results():
        user = current_user()
        if not user:
            return redirect(url_for("login"))

        finished_matches = Match.query.filter(Match.home_score.isnot(None)).order_by(Match.kickoff).all()
        board = leaderboard()
        user_points = sum(score_prediction(prediction) for prediction in user.predictions)
        return render_template(
            "results.html",
            finished_matches=finished_matches,
            board=board,
            user_points=user_points,
            score_prediction=score_prediction,
            score_details=score_details,
            round_weights=ROUND_WEIGHTS,
            round_labels=ROUND_LABELS,
        )

    @app.route("/admin/results", methods=["GET", "POST"])
    def admin_results():
        user = current_user()
        if not user:
            return redirect(url_for("login"))

        if user.username != "admin":
            flash("Доступ только для admin")
            return redirect(url_for("cabinet"))

        if request.method == "POST":
            match_id = int(request.form["match_id"])
            home_score = int(request.form["home_score"])
            away_score = int(request.form["away_score"])

            match = Match.query.get_or_404(match_id)
            match.home_score = home_score
            match.away_score = away_score
            db.session.commit()
            flash("Результат сохранен")
            return redirect(url_for("admin_results"))

        matches = Match.query.order_by(Match.kickoff).all()
        return render_template("admin_results.html", matches=matches, round_labels=ROUND_LABELS)


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
