from datetime import datetime

from app import PlayoffSeries, SeriesPrediction, User, create_app, db, leaderboard, score_series_prediction, validate_outcomes_sequence


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


def test_predictions_page_uses_current_user_data_only():
    app = make_app()
    with app.app_context():
        u1 = User(username="u1x", password_hash="x", display_name="u1x")
        u2 = User(username="u2x", password_hash="x", display_name="u2x")
        series = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="R1")
        db.session.add_all([u1, u2, series])
        db.session.flush()
        db.session.add(
            SeriesPrediction(
                user_id=u1.id,
                series_id=series.id,
                predicted_wins_a=4,
                predicted_wins_b=3,
                game_outcomes="A,B,A,B,A,B,A",
                game_scores="1:0,0:1,2:1,1:2,3:2,2:3,1:0",
            )
        )
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = u2.id
            response = client.get("/predictions")
            html = response.get_data(as_text=True)
            assert "Ваш прогноз ещё не сохранён" in html


def test_predictions_post_redirects_to_same_series_anchor():
    app = make_app()
    with app.app_context():
        user = User(username="u3x", password_hash="x", display_name="u3x")
        series = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="R1")
        db.session.add_all([user, series])
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = user.id

            response = client.post(
                "/predictions",
                data={
                    "series_id": str(series.id),
                    "predicted_wins_a": "4",
                    "predicted_wins_b": "1",
                    "game_home_scores": ["1", "2", "0", "2", "1"],
                    "game_away_scores": ["0", "1", "1", "1", "0"],
                },
                follow_redirects=False,
            )

            assert response.status_code == 302
            assert response.headers["Location"].endswith(f"/predictions#series-{series.id}")


def test_validate_outcomes_sequence_stops_after_four_wins():
    ok, _ = validate_outcomes_sequence(["A", "A", "A", "A", "B"], 4, 1)
    assert not ok


def test_r1_predictions_accept_series_only_without_match_scores():
    app = make_app()
    with app.app_context():
        user = User(username="u4x", password_hash="x", display_name="u4x")
        series = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="R1")
        db.session.add_all([user, series])
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = user.id

            response = client.post(
                "/predictions",
                data={
                    "series_id": str(series.id),
                    "predicted_wins_a": "4",
                    "predicted_wins_b": "1",
                },
                follow_redirects=False,
            )
            assert response.status_code == 302
            saved = SeriesPrediction.query.filter_by(user_id=user.id, series_id=series.id).first()
            assert saved is not None
            assert saved.game_scores == ""


def test_locked_match_cannot_be_changed_in_detailed_round():
    app = make_app()
    with app.app_context():
        admin = User(username="adm", password_hash="x", display_name="adm", is_admin=True)
        user = User(username="u5x", password_hash="x", display_name="u5x")
        series = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="SF", locked_game_indices="1")
        db.session.add_all([admin, user, series])
        db.session.flush()
        db.session.add(
            SeriesPrediction(
                user_id=user.id,
                series_id=series.id,
                predicted_wins_a=4,
                predicted_wins_b=1,
                game_outcomes="A,A,B,A,A",
                game_scores="1:0,2:1,0:1,2:1,1:0",
            )
        )
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = user.id

            response = client.post(
                "/predictions",
                data={
                    "series_id": str(series.id),
                    "predicted_wins_a": "4",
                    "predicted_wins_b": "1",
                    "game_home_scores": ["2", "2", "0", "2", "1"],
                    "game_away_scores": ["0", "1", "1", "1", "0"],
                },
                follow_redirects=False,
            )
            assert response.status_code == 302
            saved = SeriesPrediction.query.filter_by(user_id=user.id, series_id=series.id).first()
            assert saved.game_scores.startswith("1:0")


def test_team_logo_url_points_to_local_static_assets():
    app = make_app()
    from app import BASE_DIR, team_logo_url

    logos_dir = BASE_DIR / "static" / "team_logos"
    temp_logo = logos_dir / "ak_bars.png"
    temp_logo.write_bytes(b"png")
    try:
        with app.test_request_context():
            assert team_logo_url("Ак Барс").endswith("/static/team_logos/ak_bars.png")
            assert team_logo_url("Локомотив").endswith("/static/team_logos/default.svg")
            assert team_logo_url("Неизвестная команда").endswith("/static/team_logos/default.svg")
    finally:
        temp_logo.unlink(missing_ok=True)



def test_regulations_requires_auth():
    app = make_app()
    with app.test_client() as client:
        response = client.get('/regulations', follow_redirects=False)
        assert response.status_code == 302
        assert response.headers['Location'].endswith('/login')


def test_regulations_page_renders_for_logged_user():
    app = make_app()
    with app.app_context():
        user = User(username='u6x', password_hash='x', display_name='u6x')
        db.session.add(user)
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = user.id
            response = client.get('/regulations')
            assert response.status_code == 200
            html = response.get_data(as_text=True)
            assert 'Регламент турнира прогнозистов КХЛ' in html
            assert 'В 1/2 финала и в финале' in html
            assert 'Как определяется место в таблице' in html


def test_series_scoring_matches_regulations_weights():
    app = make_app()
    with app.app_context():
        user = User(username="u7x", password_hash="x", display_name="u7x")
        sf_series = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="SF")
        r1_series = PlayoffSeries(team_a="C", team_b="D", conference="E", round_code="R1")
        db.session.add_all([user, sf_series, r1_series])
        db.session.flush()

        from app import Match

        sf_games = [
            Match(series_id=sf_series.id, home_team="A", away_team="B", kickoff=datetime(2026, 3, 1, 12, 0), home_score=3, away_score=2),
            Match(series_id=sf_series.id, home_team="A", away_team="B", kickoff=datetime(2026, 3, 2, 12, 0), home_score=2, away_score=1),
            Match(series_id=sf_series.id, home_team="B", away_team="A", kickoff=datetime(2026, 3, 3, 12, 0), home_score=1, away_score=2),
            Match(series_id=sf_series.id, home_team="B", away_team="A", kickoff=datetime(2026, 3, 4, 12, 0), home_score=2, away_score=3),
        ]
        r1_games = [
            Match(series_id=r1_series.id, home_team="C", away_team="D", kickoff=datetime(2026, 3, 1, 12, 0), home_score=3, away_score=1),
            Match(series_id=r1_series.id, home_team="C", away_team="D", kickoff=datetime(2026, 3, 2, 12, 0), home_score=2, away_score=1),
            Match(series_id=r1_series.id, home_team="D", away_team="C", kickoff=datetime(2026, 3, 3, 12, 0), home_score=1, away_score=2),
            Match(series_id=r1_series.id, home_team="D", away_team="C", kickoff=datetime(2026, 3, 4, 12, 0), home_score=0, away_score=4),
        ]
        db.session.add_all(sf_games + r1_games)
        db.session.commit()

        sf_prediction = SeriesPrediction(
            user_id=user.id,
            series_id=sf_series.id,
            predicted_wins_a=4,
            predicted_wins_b=0,
            game_outcomes="A,A,A,A",
            game_scores="3:2,2:1,2:1,3:2",
        )
        r1_prediction = SeriesPrediction(
            user_id=user.id,
            series_id=r1_series.id,
            predicted_wins_a=4,
            predicted_wins_b=0,
            game_outcomes="A,A,A,A",
            game_scores="9:0,9:0,9:0,9:0",
        )

        sf_score = score_series_prediction(sf_prediction)["total"]
        r1_score = score_series_prediction(r1_prediction)["total"]

        # SF: 8 (winner series) + 8 (exact series) + 4*1 (match winners) + 4*1 (exact match scores)
        assert sf_score == 24
        # R1: only series matters (1 + 1), match-level points ignored
        assert r1_score == 2


def test_admin_results_validate_home_away_rotation_against_series_score():
    app = make_app()
    with app.app_context():
        admin = User(username="adm2", password_hash="x", display_name="adm2", is_admin=True)
        series = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="R1")
        db.session.add_all([admin, series])
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = admin.id

            response = client.post(
                "/admin/results",
                data={
                    "action": "save_results",
                    "series_id": str(series.id),
                    "wins_a": "4",
                    "wins_b": "0",
                    # home-away inputs: this would imply A wins games 1-2 and B wins games 3-4
                    # due home/away rotation, so final series score is not 4:0 for A and must be rejected
                    "game_home_scores": ["1", "1", "1", "1"],
                    "game_away_scores": ["0", "0", "0", "0"],
                },
                follow_redirects=True,
            )

            html = response.get_data(as_text=True)
            assert "Победы по матчам должны совпадать с итоговым счетом серии" in html

            from app import Match
            assert Match.query.filter_by(series_id=series.id).count() == 0


def test_leaderboard_applies_points_adjustment():
    app = make_app()
    with app.app_context():
        a = User(username="ua", password_hash="x", display_name="ua", points_adjustment=0)
        b = User(username="ub", password_hash="x", display_name="ub", points_adjustment=5)
        db.session.add_all([a, b])
        db.session.commit()

        board = leaderboard()
        assert board[0]["username"] == "ub"
        assert board[0]["points"] == 5


def test_admin_can_set_points_adjustment():
    app = make_app()
    with app.app_context():
        admin = User(username="adminset", password_hash="x", display_name="adminset", is_admin=True)
        user = User(username="plainuser", password_hash="x", display_name="plainuser")
        db.session.add_all([admin, user])
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = admin.id

            response = client.post(
                "/admin/users",
                data={"user_id": str(user.id), "action": "set_adjustment", "points_adjustment": "7"},
                follow_redirects=True,
            )
            assert response.status_code == 200

            updated = User.query.get(user.id)
            assert updated.points_adjustment == 7


def test_admin_predictions_page_shows_missing_predictions():
    app = make_app()
    with app.app_context():
        admin = User(username="adminpred", password_hash="x", display_name="adminpred", is_admin=True)
        user = User(username="u8x", password_hash="x", display_name="u8x")
        series = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="R1")
        db.session.add_all([admin, user, series])
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = admin.id

            response = client.get('/admin/predictions')
            assert response.status_code == 200
            html = response.get_data(as_text=True)
            assert 'Проверка прогнозов пользователей' in html
            assert 'Нет прогноза' in html


def test_admin_predictions_save_keeps_anchor():
    app = make_app()
    with app.app_context():
        admin = User(username="adminanchorpred", password_hash="x", display_name="adminanchorpred", is_admin=True)
        user = User(username="targetpred", password_hash="x", display_name="targetpred")
        series = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="R1")
        db.session.add_all([admin, user, series])
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = admin.id

            anchor = f"series-row-{user.id}-{series.id}"
            response = client.post(
                "/admin/predictions",
                data={
                    "action": "save_prediction",
                    "user_id": str(user.id),
                    "series_id": str(series.id),
                    "series_score": "4:2",
                    "anchor": anchor,
                },
                follow_redirects=False,
            )
            assert response.status_code == 302
            assert response.headers["Location"].endswith(f"/admin/predictions#{anchor}")


def test_predictions_page_shows_late_stages_first():
    app = make_app()
    with app.app_context():
        user = User(username="ord1", password_hash="x", display_name="ord1")
        s_qf = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="QF")
        s_r1 = PlayoffSeries(team_a="C", team_b="D", conference="W", round_code="R1")
        db.session.add_all([user, s_qf, s_r1])
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = user.id
            response = client.get('/predictions')
            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert html.find('1/4 финала') < html.find('1/8 финала')


def test_admin_results_redirects_back_to_series_anchor():
    app = make_app()
    with app.app_context():
        admin = User(username="admanchor", password_hash="x", display_name="admanchor", is_admin=True)
        series = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="R1")
        db.session.add_all([admin, series])
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = admin.id

            response = client.post(
                '/admin/results',
                data={
                    'action': 'toggle_lock',
                    'series_id': str(series.id),
                    'game_index': '1',
                },
                follow_redirects=False,
            )
            assert response.status_code == 302
            assert response.headers['Location'].endswith(f'/admin/results#series-{series.id}')


def test_admin_matches_shows_late_rounds_first():
    app = make_app()
    with app.app_context():
        admin = User(username="adminordm", password_hash="x", display_name="adminordm", is_admin=True)
        s_r1 = PlayoffSeries(team_a="R1A", team_b="R1B", conference="W", round_code="R1")
        s_qf = PlayoffSeries(team_a="QFA", team_b="QFB", conference="W", round_code="QF")
        s_sf = PlayoffSeries(team_a="SFA", team_b="SFB", conference="W", round_code="SF")
        db.session.add_all([admin, s_r1, s_qf, s_sf])
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = admin.id
            response = client.get("/admin/matches")
            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert html.find("SFA — SFB") < html.find("QFA — QFB") < html.find("R1A — R1B")


def test_admin_results_shows_late_rounds_first_inside_conference():
    app = make_app()
    with app.app_context():
        admin = User(username="adminordr", password_hash="x", display_name="adminordr", is_admin=True)
        s_r1 = PlayoffSeries(team_a="R1X", team_b="R1Y", conference="W", round_code="R1")
        s_sf = PlayoffSeries(team_a="SFX", team_b="SFY", conference="W", round_code="SF")
        db.session.add_all([admin, s_r1, s_sf])
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = admin.id
            response = client.get("/admin/results")
            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert html.find("SFX") < html.find("R1X")


def test_admin_matches_rejects_same_teams_and_duplicate():
    app = make_app()
    with app.app_context():
        admin = User(username="adminvalid", password_hash="x", display_name="adminvalid", is_admin=True)
        existing = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="QF", prediction_deadline=datetime(2026, 5, 1, 12, 0))
        db.session.add_all([admin, existing])
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = admin.id

            same_teams = client.post(
                "/admin/matches",
                data={
                    "team_a": "A",
                    "team_b": "A",
                    "conference": "W",
                    "round_code": "QF",
                    "prediction_deadline": "2026-05-02T12:00",
                },
                follow_redirects=True,
            )
            assert "Команды серии должны быть разными" in same_teams.get_data(as_text=True)

            duplicate = client.post(
                "/admin/matches",
                data={
                    "team_a": "A",
                    "team_b": "B",
                    "conference": "W",
                    "round_code": "QF",
                    "prediction_deadline": "2026-05-02T12:00",
                },
                follow_redirects=True,
            )
            assert "Такая серия уже существует" in duplicate.get_data(as_text=True)


def test_admin_matches_rejects_past_deadline():
    app = make_app()
    with app.app_context():
        admin = User(username="adminpast", password_hash="x", display_name="adminpast", is_admin=True)
        db.session.add(admin)
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = admin.id

            response = client.post(
                "/admin/matches",
                data={
                    "team_a": "X",
                    "team_b": "Y",
                    "conference": "W",
                    "round_code": "SF",
                    "prediction_deadline": "2020-01-01T12:00",
                },
                follow_redirects=True,
            )
            html = response.get_data(as_text=True)
            assert "Дедлайн не может быть в прошлом" in html


def test_results_page_shows_leader_highlight_and_insights():
    app = make_app()
    with app.app_context():
        leader_user = User(username="leader_u", password_hash="x", display_name="Leader")
        other_user = User(username="other_u", password_hash="x", display_name="Other")
        series = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="R1")
        db.session.add_all([leader_user, other_user, series])
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
        db.session.add_all(
            [
                SeriesPrediction(user_id=leader_user.id, series_id=series.id, predicted_wins_a=4, predicted_wins_b=0, game_outcomes="", game_scores=""),
                SeriesPrediction(user_id=other_user.id, series_id=series.id, predicted_wins_a=4, predicted_wins_b=3, game_outcomes="", game_scores=""),
            ]
        )
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = leader_user.id
            response = client.get("/results")
            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert "Факты по текущему ПО" in html
            assert "👑" in html
            assert "Leader" in html
            assert "current-user-row" in html


def test_results_page_shows_tied_leaders_in_facts():
    app = make_app()
    with app.app_context():
        u1 = User(username="u1lead", password_hash="x", display_name="U1")
        u2 = User(username="u2lead", password_hash="x", display_name="U2")
        db.session.add_all([u1, u2])
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = u1.id
            response = client.get("/results")
            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert "Лидеры по очкам" in html
            assert "U1, U2" in html or "U2, U1" in html


def test_predictions_page_hides_empty_round_and_conference_blocks():
    app = make_app()
    with app.app_context():
        user = User(username="hideempty", password_hash="x", display_name="hideempty")
        # only one series in one conference/round
        series = PlayoffSeries(team_a="A", team_b="B", conference="W", round_code="QF")
        db.session.add_all([user, series])
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = user.id
            response = client.get("/predictions")
            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert "Пока нет серий на этой стадии в конференции" not in html


def test_live_page_requires_auth():
    app = make_app()
    with app.test_client() as client:
        response = client.get("/live", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")


def test_live_page_renders_grouped_events(monkeypatch):
    app = make_app()
    with app.app_context():
        user = User(username="liveuser", password_hash="x", display_name="liveuser")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    import app as app_module

    monkeypatch.setattr(
        app_module,
        "fetch_khl_live_groups",
        lambda: {
            "upcoming": [
                {
                    "home_team": "Team A",
                    "away_team": "Team B",
                    "home_score": None,
                    "away_score": None,
                    "date_label": "10.04",
                    "time_label": "19:30",
                    "status": "",
                }
            ],
            "live": [
                {
                    "home_team": "Team C",
                    "away_team": "Team D",
                    "home_score": 2,
                    "away_score": 1,
                    "date_label": "08.04",
                    "time_label": "20:00",
                    "status": "LIVE",
                }
            ],
            "recent": [
                {
                    "home_team": "Team E",
                    "away_team": "Team F",
                    "home_score": 4,
                    "away_score": 3,
                    "date_label": "07.04",
                    "time_label": "18:00",
                    "status": "Match Finished",
                }
            ],
            "error": "",
        },
    )

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
        response = client.get("/live")
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "LIVE-центр КХЛ" in html
        assert "Текущие (LIVE)" in html
        assert "Предстоящие (7 дней)" in html
        assert "Прошедшие (7 дней)" in html
        assert "Team C" in html
        assert "Team A" in html
        assert "4" in html
