export interface TranscriptSegment {
  start_seconds: number;
  end_seconds: number;
  text: string;
}

export interface VideoMetadata {
  id: string;
  title: string | null;
  url: string;
  thumbnail_url: string;
  duration_seconds: number | null;
}

export interface ProcessVideoResponse {
  status: "ready";
  mode: "mock" | "real";
  video: VideoMetadata;
  transcript: TranscriptSegment[];
}

export interface HealthResponse {
  status: "ok";
  service: "videowise-api";
  mode: "mock";
}

export interface ErrorResponse {
  error: {
    code: string;
    message: string;
  };
}

export interface ChatRequest {
  video_id: string;
  question: string;
  conversation_id: string | null;
}

export interface ChatResponse {
  video_id: string;
  conversation_id: string;
  mode: "real";
  answer: string;
  sources: TranscriptSegment[];
}
