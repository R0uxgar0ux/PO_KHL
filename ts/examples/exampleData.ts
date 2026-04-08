import { buildLeaderboard, ParticipantPredictions, SeriesResult, MatchResult } from '../src/predictorScoring';

const seriesResults: SeriesResult[] = [
  { stage: 'R16', seriesId: 'r16-1', winnerTeamId: 'lokomotiv', winnerWins: 4, loserWins: 1 },
  { stage: 'FINAL', seriesId: 'f-1', winnerTeamId: 'ska', winnerWins: 4, loserWins: 2 },
];

const matchResults: MatchResult[] = [
  { stage: 'FINAL', seriesId: 'f-1', matchId: 'g1', winnerTeamId: 'ska', score: { home: 3, away: 2 } },
  { stage: 'FINAL', seriesId: 'f-1', matchId: 'g2', winnerTeamId: 'ska', score: { home: 2, away: 1 } },
];

const participants: ParticipantPredictions[] = [
  {
    participantId: 'alice',
    seriesPredictions: [
      { stage: 'R16', seriesId: 'r16-1', winnerTeamId: 'lokomotiv', winnerWins: 4, loserWins: 1 },
      { stage: 'FINAL', seriesId: 'f-1', winnerTeamId: 'ska', winnerWins: 4, loserWins: 2 },
    ],
    matchPredictions: [
      { stage: 'FINAL', seriesId: 'f-1', matchId: 'g1', winnerTeamId: 'ska', score: { home: 3, away: 2 } },
      { stage: 'FINAL', seriesId: 'f-1', matchId: 'g2', winnerTeamId: 'ska', score: { home: 2, away: 1 } },
    ],
  },
  {
    participantId: 'bob',
    seriesPredictions: [
      { stage: 'R16', seriesId: 'r16-1', winnerTeamId: 'spartak', winnerWins: 4, loserWins: 3 },
      { stage: 'FINAL', seriesId: 'f-1', winnerTeamId: 'ska', winnerWins: 4, loserWins: 3 },
    ],
    matchPredictions: [
      { stage: 'FINAL', seriesId: 'f-1', matchId: 'g1', winnerTeamId: 'ska', score: { home: 4, away: 2 } },
      { stage: 'FINAL', seriesId: 'f-1', matchId: 'g2', winnerTeamId: 'opponent', score: { home: 1, away: 3 } },
    ],
  },
];

const table = buildLeaderboard(participants, seriesResults, matchResults);
console.log(JSON.stringify(table, null, 2));
