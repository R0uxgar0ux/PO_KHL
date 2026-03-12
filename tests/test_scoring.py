from datetime import datetime

from app import Match, Prediction, User, create_app, db, leaderboard, score_details, score_prediction


def make_app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SECRET_KEY": "test",
        }
    )
    return app


def test_scoring_with_round_weight():
    app = make_app()
    with app.app_context():
        user = User(username="u1", password_hash="x")
        final_match = Match(
            home_team="A",
            away_team="B",
            kickoff=datetime(2026, 3, 10, 12, 0),
            round_code="F",
            home_score=3,
            away_score=2,
        )
        db.session.add_all([user, final_match])
        db.session.commit()

        exact = Prediction(user_id=user.id, match_id=final_match.id, predicted_home=3, predicted_away=2)
        assert score_prediction(exact) == 20  # (2 + 2 + 1 + 4) * 2.2 -> round(19.8)=20


def test_scoring_components_outcome_only():
    app = make_app()
    with app.app_context():
        user = User(username="u1", password_hash="x")
        match = Match(
            home_team="A",
            away_team="B",
            kickoff=datetime(2026, 3, 10, 12, 0),
            round_code="QF",
            home_score=4,
            away_score=1,
        )
        db.session.add_all([user, match])
        db.session.commit()

        prediction = Prediction(user_id=user.id, match_id=match.id, predicted_home=2, predicted_away=0)
        details = score_details(prediction)

        assert details["base"] == 4  # исход + разница
        assert details["total"] == 5  # 4 * 1.25


def test_leaderboard_tiebreak_exact_hits():
    app = make_app()
    with app.app_context():
        a = User(username="alice", password_hash="x")
        b = User(username="bob", password_hash="x")
        match = Match(home_team="A", away_team="B", kickoff=datetime(2026, 3, 10, 12, 0), round_code="R1", home_score=1, away_score=1)
        db.session.add_all([a, b, match])
        db.session.commit()

        pa = Prediction(user_id=a.id, match_id=match.id, predicted_home=1, predicted_away=1)
        pb = Prediction(user_id=b.id, match_id=match.id, predicted_home=2, predicted_away=2)
        db.session.add_all([pa, pb])
        db.session.commit()

        board = leaderboard()
        assert board[0]["display_name"] == "alice"
        assert board[0]["exact_hits"] == 1
