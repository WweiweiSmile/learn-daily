export type BookStatus = 'parsing' | 'ready' | 'failed';
export type TaskStatus = 'pending' | 'running' | 'done' | 'failed';
export type DayStatus = 'pending' | 'done';
export type Verdict = 'correct' | 'partial' | 'off';
export type QuestionKind = 'single' | 'short';

export interface Book {
  id: number;
  title: string;
  source_filename: string | null;
  source_type: 'pdf' | 'text';
  status: BookStatus;
  error: string | null;
  warning: string | null;
  total_chars: number;
  day_count: number;
  completed_days: number;
  created_at: string;
}

export interface DaySummary {
  id: number;
  day_index: number;
  title: string;
  char_count: number;
  status: DayStatus;
  section_count: number;
  has_lesson: boolean;
  question_count: number;
}

export interface BookDetail {
  book: Book;
  days: DaySummary[];
}

export interface Section {
  id: number;
  title: string | null;
  content: string;
}

export interface Lesson {
  status: TaskStatus;
  content: string | null;
  error: string | null;
}

export interface Question {
  id: number;
  idx: number;
  kind: QuestionKind;
  stem: string;
  options: string[];
}

export interface Attempt {
  id: number;
  question_id: number;
  user_answer: string;
  concept: string;
  status: TaskStatus;
  verdict: Verdict | null;
  score: number | null;
  got_right: string[];
  got_wrong: string[];
  guidance: string | null;
  takeaway: string | null;
  error: string | null;
  /** 只有批改完成后后端才给 */
  answer_key: string | null;
}

export interface Concept {
  id: number;
  day_id: number;
  name: string;
  summary: string;
}

export interface DayDetail {
  id: number;
  day_index: number;
  title: string;
  status: DayStatus;
  char_count: number;
  sections: Section[];
  lesson: Lesson | null;
  quiz_status: TaskStatus;
  quiz_error: string | null;
  questions: Question[];
  attempts: Attempt[];
  concepts: Concept[];
}

export interface LearnedItem {
  concept: string;
  evidence: string;
}

export interface GapItem {
  concept: string;
  evidence: string;
  suggestion: string;
}

export interface DiagnosisResult {
  summary: string;
  learned: LearnedItem[];
  gaps: GapItem[];
  blind_spots: string[];
  pattern: string;
  next_steps: string[];
}

export interface Diagnosis {
  id: number | null;
  book_id: number | null;
  status: TaskStatus;
  error: string | null;
  result: DiagnosisResult | null;
  is_stale: boolean;
  evidence: { concepts: number; misconceptions: number; graded: number };
}
