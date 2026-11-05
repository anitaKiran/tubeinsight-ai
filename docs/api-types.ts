/** tubeInsight-ai Phase 2 prepared-video contract. Timestamps are seconds. */
export interface VideoMetadata {
  id: string;
  title: string | null;
  url: string;
  thumbnail_url: string;
  duration_seconds: number | null;
}

export interface TranscriptSegment {
  start_seconds: number;
  end_seconds: number;
  text: string;
}

export interface SourceSegment extends TranscriptSegment {}

export interface VideoProcessRequest {
  url: string;
}

export interface VideoProcessResponse {
  status: "ready";
  mode: "real";
  video: VideoMetadata;
  transcript: TranscriptSegment[];
}

export interface ChatRequest {
  video_id: string;
  question: string;
  conversation_id?: string | null;
}

export interface ChatResponse {
  video_id: string;
  conversation_id: string;
  mode: "mock";
  answer: string;
  sources: SourceSegment[];
}

export interface ApiError {
  code: string;
  message: string;
}

export interface ErrorResponse {
  error: ApiError;
}

export interface HealthResponse {
  status: "ok";
  service: "videowise-api";
  mode: "mock";
}
