from datetime import datetime

from app import PlayoffSeries, SeriesPrediction, User, create_app, db, leaderboard, score_series_prediction


def make_app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SECRET_KEY": "test",
        }
    )
    return app


def test_series_scoring_includes_exact_match_scores_bonus():
    app = make_app()
    with app.app_context():
        user = User(username="u1", password_hash="x", display_name="u1")
        series = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="F")
        db.session.add_all([user, series])
        db.session.flush()

        from app import Match

        games = [
            Match(series_id=series.id, home_team="A", away_team="B", kickoff=datetime(2026, 3, 1, 12, 0), home_score=3, away_score=1),
            Match(series_id=series.id, home_team="A", away_team="B", kickoff=datetime(2026, 3, 2, 12, 0), home_score=2, away_score=1),
            Match(series_id=series.id, home_team="B", away_team="A", kickoff=datetime(2026, 3, 3, 12, 0), home_score=4, away_score=2),
            Match(series_id=series.id, home_team="B", away_team="A", kickoff=datetime(2026, 3, 4, 12, 0), home_score=1, away_score=2),
            Match(series_id=series.id, home_team="A", away_team="B", kickoff=datetime(2026, 3, 5, 12, 0), home_score=5, away_score=0),
        ]
        db.session.add_all(games)
        db.session.commit()

        perfect = SeriesPrediction(
            user_id=user.id,
            series_id=series.id,
            predicted_wins_a=4,
            predicted_wins_b=1,
            game_outcomes="A,A,B,A,A",
            game_scores="3:1,2:1,2:4,2:1,5:0",
        )
        near = SeriesPrediction(
            user_id=user.id,
            series_id=series.id,
            predicted_wins_a=4,
            predicted_wins_b=1,
            game_outcomes="A,A,B,A,A",
            game_scores="4:1,2:1,2:4,2:1,5:0",
        )
        perfect_score = score_series_prediction(perfect)["total"]
        near_score = score_series_prediction(near)["total"]
        assert perfect_score > near_score


def test_leaderboard_uses_series_predictions():
    app = make_app()
    with app.app_context():
        a = User(username="alice", password_hash="x", display_name="alice")
        b = User(username="bob", password_hash="x", display_name="bob")
        series = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="R1")
        db.session.add_all([a, b, series])
        db.session.flush()

        from app import Match

        db.session.add_all(
            [
                Match(series_id=series.id, home_team="A", away_team="B", kickoff=datetime(2026, 3, 1, 12, 0), home_score=2, away_score=1),
                Match(series_id=series.id, home_team="A", away_team="B", kickoff=datetime(2026, 3, 2, 12, 0), home_score=3, away_score=1),
                Match(series_id=series.id, home_team="B", away_team="A", kickoff=datetime(2026, 3, 3, 12, 0), home_score=1, away_score=2),
                Match(series_id=series.id, home_team="B", away_team="A", kickoff=datetime(2026, 3, 4, 12, 0), home_score=2, away_score=3),
            ]
        )
        db.session.commit()

        db.session.add_all(
            [
                SeriesPrediction(
                    user_id=a.id,
                    series_id=series.id,
                    predicted_wins_a=4,
                    predicted_wins_b=0,
                    game_outcomes="A,A,A,A",
                    game_scores="2:1,3:1,2:1,3:2",
                ),
                SeriesPrediction(
                    user_id=b.id,
                    series_id=series.id,
                    predicted_wins_a=4,
                    predicted_wins_b=3,
                    game_outcomes="A,B,A,B,A,B,A",
                    game_scores="2:1,2:3,1:2,2:3,2:1,1:2,2:1",
                ),
            ]
        )
        db.session.commit()

        board = leaderboard()
        assert board[0]["display_name"] == "alice"
