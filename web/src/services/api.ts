import { BASE_URL, request } from './request';
import type { Attempt, Book, BookDetail, DayDetail, DaySummary, Diagnosis } from '../models/types';

export const api = {
  listBooks: () => request<Book[]>('/books'),

  getBook: (id: number) => request<BookDetail>(`/books/${id}`),

  deleteBook: (id: number) => request<{ deleted: boolean }>(`/books/${id}`, { method: 'DELETE' }),

  createTextBook: (title: string, text: string) =>
    request<Book>('/books/text', { method: 'POST', data: { title, text } }),

  getDay: (id: number) => request<DayDetail>(`/days/${id}`),

  startLesson: (id: number) => request<DayDetail>(`/days/${id}/lesson`, { method: 'POST' }),

  startQuiz: (id: number) => request<DayDetail>(`/days/${id}/quiz`, { method: 'POST' }),

  submitAnswer: (questionId: number, answer: string) =>
    request<Attempt>(`/questions/${questionId}/attempts`, { method: 'POST', data: { answer } }),

  completeDay: (id: number) => request<DaySummary>(`/days/${id}/complete`, { method: 'POST' }),

  reopenDay: (id: number) => request<DaySummary>(`/days/${id}/reopen`, { method: 'POST' }),

  getDiagnosis: (bookId?: number) =>
    request<Diagnosis>(`/diagnosis${bookId == null ? '' : `?book_id=${bookId}`}`),

  startDiagnosis: (bookId?: number) =>
    request<Diagnosis>(`/diagnosis${bookId == null ? '' : `?book_id=${bookId}`}`, {
      method: 'POST',
    }),
};

export interface PickedFile {
  name: string;
  file: File;
}

/**
 * 选一个 PDF。
 *
 * 只在 H5 下工作：Taro 没有跨端的文件选择 API（`Taro.chooseMessageFile` 只有小程序端有），
 * 所以这里直接造一个 DOM input。要在微信小程序里跑，得换一条完全不同的
 * 选择 + 上传路径（chooseMessageFile + Taro.uploadFile），M1 没做。
 */
export function pickPdf(): Promise<PickedFile | null> {
  if (process.env.TARO_ENV !== 'h5') {
    return Promise.reject(new Error('M1 只支持在浏览器里上传 PDF'));
  }
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/pdf,.pdf';
    input.onchange = () => {
      const file = input.files?.[0];
      resolve(file ? { name: file.name, file } : null);
    };
    input.click();
  });
}

/**
 * 传 PDF。
 *
 * 走原生 fetch 而不是 Taro.uploadFile：H5 端 uploadFile 在 4xx/5xx 时也走 success，
 * 状态码还得自己判，而且它要的是 filePath 不是 File，绕一圈没必要。
 */
export async function uploadPdf(source: PickedFile, title: string): Promise<Book> {
  const form = new FormData();
  form.append('file', source.file, source.name);
  form.append('title', title);

  const response = await fetch(`${BASE_URL}/books/pdf`, { method: 'POST', body: form });
  if (!response.ok) {
    let detail = '';
    try {
      const body = await response.json();
      if (body && typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* 错误体不是 JSON 就算了，用状态码兜底 */
    }
    throw new Error(detail || `上传失败（${response.status}）`);
  }
  return (await response.json()) as Book;
}
