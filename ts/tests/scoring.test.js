const test = require('node:test');
const assert = require('node:assert/strict');
const scoring = require('../../dist/ts/src/predictorScoring.js');

test('R16 series scoring is binary and uses 1+1', () => {
  const prediction = { stage: 'R16', seriesId: 's1', winnerTeamId: 'A', winnerWins: 4, loserWins: 2 };
  const result = { stage: 'R16', seriesId: 's1', winnerTeamId: 'A', winnerWins: 4, loserWins: 2 };
  const r = scoring.scoreSeries('R16', prediction, result);
  assert.equal(r.points, 2);
  assert.equal(r.winnerCorrect, true);
  assert.equal(r.exactSeriesScoreCorrect, true);
});

test('SF match scoring gives winner+exact bonus', () => {
  const prediction = {
    stage: 'SF', seriesId: 's2', matchId: 'm1', winnerTeamId: 'HOME', homeTeamId: 'HOME', awayTeamId: 'AWAY', score: { home: 3, away: 2 }
  };
  const result = {
    stage: 'SF', seriesId: 's2', matchId: 'm1', winnerTeamId: 'HOME', homeTeamId: 'HOME', awayTeamId: 'AWAY', score: { home: 3, away: 2 }
  };
  const r = scoring.scoreMatch('SF', prediction, result);
  assert.equal(r.points, 2);
});

test('R16 and QF ignore match points', () => {
  const prediction = { stage: 'QF', seriesId: 's3', matchId: 'm1', winnerTeamId: 'A', score: { home: 1, away: 0 } };
  const result = { stage: 'QF', seriesId: 's3', matchId: 'm1', winnerTeamId: 'A', score: { home: 1, away: 0 } };
  const r = scoring.scoreMatch('QF', prediction, result);
  assert.equal(r.points, 0);
});

test('leaderboard tie-breakers: final > sf > exact series > exact match > correct series winner', () => {
  const seriesResults = [
    { stage: 'FINAL', seriesId: 'f1', winnerTeamId: 'A', winnerWins: 4, loserWins: 3 },
    { stage: 'SF', seriesId: 'sf1', winnerTeamId: 'X', winnerWins: 4, loserWins: 2 },
  ];
  const matchResults = [
    { stage: 'FINAL', seriesId: 'f1', matchId: 'g1', winnerTeamId: 'A', score: { home: 2, away: 1 } },
  ];

  const p1 = {
    participantId: 'alpha',
    seriesPredictions: [
      { stage: 'FINAL', seriesId: 'f1', winnerTeamId: 'A', winnerWins: 4, loserWins: 3 },
      { stage: 'SF', seriesId: 'sf1', winnerTeamId: 'Y', winnerWins: 4, loserWins: 3 },
    ],
    matchPredictions: [{ stage: 'FINAL', seriesId: 'f1', matchId: 'g1', winnerTeamId: 'A', score: { home: 2, away: 1 } }],
  };

  const p2 = {
    participantId: 'beta',
    seriesPredictions: [
      { stage: 'FINAL', seriesId: 'f1', winnerTeamId: 'B', winnerWins: 4, loserWins: 3 },
      { stage: 'SF', seriesId: 'sf1', winnerTeamId: 'X', winnerWins: 4, loserWins: 2 },
    ],
    matchPredictions: [{ stage: 'FINAL', seriesId: 'f1', matchId: 'g1', winnerTeamId: 'A', score: { home: 2, away: 1 } }],
  };

  const table = scoring.buildLeaderboard([p1, p2], seriesResults, matchResults);
  assert.equal(table[0].participantId, 'alpha');
});

test('validation rejects contradictory winner and exact match score', () => {
  const prediction = {
    stage: 'FINAL', seriesId: 'f2', matchId: 'g1', winnerTeamId: 'AWAY', homeTeamId: 'HOME', awayTeamId: 'AWAY', score: { home: 3, away: 1 }
  };
  const errors = scoring.validateMatchPrediction(prediction);
  assert.equal(errors.some((e) => e.field === 'winnerTeamId'), true);
});
