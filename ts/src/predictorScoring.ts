export type Stage = 'R16' | 'QF' | 'SF' | 'FINAL';
export type TeamId = string;

export interface StageWeights {
  seriesWinner: number;
  seriesScore: number;
  gameWinner: number;
  gameScore: number;
}

export const WEIGHTS: Record<Stage, StageWeights> = {
  R16: { seriesWinner: 1, seriesScore: 1, gameWinner: 0, gameScore: 0 },
  QF: { seriesWinner: 2, seriesScore: 2, gameWinner: 0, gameScore: 0 },
  SF: { seriesWinner: 8, seriesScore: 8, gameWinner: 1, gameScore: 1 },
  FINAL: { seriesWinner: 16, seriesScore: 16, gameWinner: 2, gameScore: 2 },
};

const VALID_STAGES: Stage[] = ['R16', 'QF', 'SF', 'FINAL'];

export interface SeriesScore {
  winnerWins: 4;
  loserWins: 0 | 1 | 2 | 3;
}

export interface MatchScore {
  home: number;
  away: number;
}

export interface PlayoffSeries {
  id: string;
  stage: Stage;
  teamAId: TeamId;
  teamBId: TeamId;
}

export interface PlayoffMatch {
  id: string;
  stage: Stage;
  seriesId: string;
  homeTeamId: TeamId;
  awayTeamId: TeamId;
}

export interface SeriesPrediction extends SeriesScore {
  stage: Stage;
  seriesId: string;
  winnerTeamId: TeamId;
}

export interface SeriesResult extends SeriesScore {
  stage: Stage;
  seriesId: string;
  winnerTeamId: TeamId;
}

export interface MatchPrediction {
  stage: Stage;
  seriesId: string;
  matchId: string;
  winnerTeamId: TeamId;
  score: MatchScore;
  homeTeamId?: TeamId;
  awayTeamId?: TeamId;
}

export interface MatchResult {
  stage: Stage;
  seriesId: string;
  matchId: string;
  winnerTeamId: TeamId;
  score: MatchScore;
  homeTeamId?: TeamId;
  awayTeamId?: TeamId;
}

export interface ParticipantPredictions {
  participantId: string;
  seriesPredictions: SeriesPrediction[];
  matchPredictions: MatchPrediction[];
}

export interface SeriesScoreBreakdown {
  points: number;
  winnerCorrect: boolean;
  exactSeriesScoreCorrect: boolean;
}

export interface MatchScoreBreakdown {
  points: number;
  winnerCorrect: boolean;
  exactMatchScoreCorrect: boolean;
}

export interface ParticipantStanding {
  participantId: string;
  points_r16: number;
  points_qf: number;
  points_sf: number;
  points_final: number;
  total_points: number;
  exact_series_scores: number;
  exact_match_scores: number;
  correct_series_winners: number;
}

export interface ValidationError {
  field: string;
  message: string;
}

export class ScoringValidationError extends Error {
  constructor(public readonly errors: ValidationError[]) {
    super(`Validation failed: ${errors.map((e) => `${e.field}: ${e.message}`).join('; ')}`);
  }
}

function assertValidStage(stage: string, field: string): asserts stage is Stage {
  if (!VALID_STAGES.includes(stage as Stage)) {
    throw new ScoringValidationError([{ field, message: `Unknown stage: ${stage}` }]);
  }
}

function ensureNonNegativeInt(value: number, field: string): ValidationError | null {
  if (!Number.isInteger(value) || value < 0) {
    return { field, message: 'Must be a non-negative integer' };
  }
  return null;
}

export function validateSeriesScore(score: SeriesScore): ValidationError[] {
  const errors: ValidationError[] = [];
  if (score.winnerWins !== 4) {
    errors.push({ field: 'winnerWins', message: 'Winner wins must be exactly 4' });
  }
  if (![0, 1, 2, 3].includes(score.loserWins)) {
    errors.push({ field: 'loserWins', message: 'Loser wins must be one of: 0, 1, 2, 3' });
  }
  return errors;
}

export function validateMatchScore(score: MatchScore): ValidationError[] {
  const errors: ValidationError[] = [];
  const homeErr = ensureNonNegativeInt(score.home, 'score.home');
  const awayErr = ensureNonNegativeInt(score.away, 'score.away');
  if (homeErr) errors.push(homeErr);
  if (awayErr) errors.push(awayErr);
  if (score.home === score.away) {
    errors.push({ field: 'score', message: 'Draw is not allowed in playoff match result' });
  }
  return errors;
}

function deriveWinnerFromScore(score: MatchScore, homeTeamId?: TeamId, awayTeamId?: TeamId): TeamId | null {
  if (!homeTeamId || !awayTeamId) return null;
  return score.home > score.away ? homeTeamId : awayTeamId;
}

export function validateSeriesPrediction(prediction: SeriesPrediction): ValidationError[] {
  const errors: ValidationError[] = [];
  try {
    assertValidStage(prediction.stage, 'stage');
  } catch (e) {
    if (e instanceof ScoringValidationError) errors.push(...e.errors);
  }
  errors.push(...validateSeriesScore(prediction));
  if (!prediction.seriesId) errors.push({ field: 'seriesId', message: 'seriesId is required' });
  if (!prediction.winnerTeamId) errors.push({ field: 'winnerTeamId', message: 'winnerTeamId is required' });
  return errors;
}

export function validateSeriesResult(result: SeriesResult): ValidationError[] {
  return validateSeriesPrediction(result);
}

export function validateMatchPrediction(prediction: MatchPrediction): ValidationError[] {
  const errors: ValidationError[] = [];
  try {
    assertValidStage(prediction.stage, 'stage');
  } catch (e) {
    if (e instanceof ScoringValidationError) errors.push(...e.errors);
  }
  if (!prediction.seriesId) errors.push({ field: 'seriesId', message: 'seriesId is required' });
  if (!prediction.matchId) errors.push({ field: 'matchId', message: 'matchId is required' });
  if (!prediction.winnerTeamId) errors.push({ field: 'winnerTeamId', message: 'winnerTeamId is required' });
  errors.push(...validateMatchScore(prediction.score));

  const derived = deriveWinnerFromScore(prediction.score, prediction.homeTeamId, prediction.awayTeamId);
  if (derived && derived !== prediction.winnerTeamId) {
    errors.push({ field: 'winnerTeamId', message: 'Contradicts exact match score winner' });
  }
  return errors;
}

export function validateMatchResult(result: MatchResult): ValidationError[] {
  return validateMatchPrediction(result);
}

export function scoreSeries(stage: Stage, prediction: SeriesPrediction, result: SeriesResult): SeriesScoreBreakdown {
  assertValidStage(stage, 'stage');
  const pErr = validateSeriesPrediction(prediction);
  const rErr = validateSeriesResult(result);
  if (pErr.length || rErr.length) throw new ScoringValidationError([...pErr, ...rErr]);
  if (prediction.stage !== stage || result.stage !== stage) {
    throw new ScoringValidationError([{ field: 'stage', message: 'Stage mismatch' }]);
  }
  if (prediction.seriesId !== result.seriesId) {
    throw new ScoringValidationError([{ field: 'seriesId', message: 'Series id mismatch' }]);
  }

  const winnerCorrect = prediction.winnerTeamId === result.winnerTeamId;
  const exactSeriesScoreCorrect =
    winnerCorrect && prediction.winnerWins === result.winnerWins && prediction.loserWins === result.loserWins;

  const points =
    (winnerCorrect ? WEIGHTS[stage].seriesWinner : 0) +
    (exactSeriesScoreCorrect ? WEIGHTS[stage].seriesScore : 0);

  return { points, winnerCorrect, exactSeriesScoreCorrect };
}

export function scoreMatch(stage: Stage, prediction: MatchPrediction, result: MatchResult): MatchScoreBreakdown {
  assertValidStage(stage, 'stage');
  const pErr = validateMatchPrediction(prediction);
  const rErr = validateMatchResult(result);
  if (pErr.length || rErr.length) throw new ScoringValidationError([...pErr, ...rErr]);
  if (prediction.stage !== stage || result.stage !== stage) {
    throw new ScoringValidationError([{ field: 'stage', message: 'Stage mismatch' }]);
  }
  if (prediction.seriesId !== result.seriesId || prediction.matchId !== result.matchId) {
    throw new ScoringValidationError([{ field: 'matchId', message: 'Match identity mismatch' }]);
  }

  const winnerCorrect = prediction.winnerTeamId === result.winnerTeamId;
  const exactMatchScoreCorrect =
    prediction.score.home === result.score.home && prediction.score.away === result.score.away;

  const points =
    (winnerCorrect ? WEIGHTS[stage].gameWinner : 0) +
    (exactMatchScoreCorrect ? WEIGHTS[stage].gameScore : 0);

  return { points, winnerCorrect, exactMatchScoreCorrect };
}

export function scoreParticipant(
  participant: ParticipantPredictions,
  seriesResults: SeriesResult[],
  matchResults: MatchResult[]
): ParticipantStanding {
  const seriesResultById = new Map(seriesResults.map((item) => [item.seriesId, item]));
  const matchResultById = new Map(matchResults.map((item) => [`${item.seriesId}::${item.matchId}`, item]));

  const standing: ParticipantStanding = {
    participantId: participant.participantId,
    points_r16: 0,
    points_qf: 0,
    points_sf: 0,
    points_final: 0,
    total_points: 0,
    exact_series_scores: 0,
    exact_match_scores: 0,
    correct_series_winners: 0,
  };

  for (const prediction of participant.seriesPredictions) {
    const result = seriesResultById.get(prediction.seriesId);
    if (!result) continue;
    const breakdown = scoreSeries(prediction.stage, prediction, result);

    if (prediction.stage === 'R16') standing.points_r16 += breakdown.points;
    if (prediction.stage === 'QF') standing.points_qf += breakdown.points;
    if (prediction.stage === 'SF') standing.points_sf += breakdown.points;
    if (prediction.stage === 'FINAL') standing.points_final += breakdown.points;

    if (breakdown.winnerCorrect) standing.correct_series_winners += 1;
    if (breakdown.exactSeriesScoreCorrect) standing.exact_series_scores += 1;
  }

  for (const prediction of participant.matchPredictions) {
    const key = `${prediction.seriesId}::${prediction.matchId}`;
    const result = matchResultById.get(key);
    if (!result) continue;
    const breakdown = scoreMatch(prediction.stage, prediction, result);

    if (prediction.stage === 'SF') standing.points_sf += breakdown.points;
    if (prediction.stage === 'FINAL') standing.points_final += breakdown.points;
    if (breakdown.exactMatchScoreCorrect) standing.exact_match_scores += 1;
  }

  standing.total_points = standing.points_r16 + standing.points_qf + standing.points_sf + standing.points_final;
  return standing;
}

export function buildLeaderboard(
  participants: ParticipantPredictions[],
  seriesResults: SeriesResult[],
  matchResults: MatchResult[]
): ParticipantStanding[] {
  return participants
    .map((participant) => scoreParticipant(participant, seriesResults, matchResults))
    .sort((a, b) => {
      if (b.total_points !== a.total_points) return b.total_points - a.total_points;
      if (b.points_final !== a.points_final) return b.points_final - a.points_final;
      if (b.points_sf !== a.points_sf) return b.points_sf - a.points_sf;
      if (b.exact_series_scores !== a.exact_series_scores) return b.exact_series_scores - a.exact_series_scores;
      if (b.exact_match_scores !== a.exact_match_scores) return b.exact_match_scores - a.exact_match_scores;
      if (b.correct_series_winners !== a.correct_series_winners) return b.correct_series_winners - a.correct_series_winners;
      return a.participantId.localeCompare(b.participantId);
    });
}
