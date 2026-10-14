import { BASE_URL, refreshAccessToken, request } from './request';
import { getAccessToken } from '../utils/authStorage';
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
 *
 * 代价是**绕开了 request()，token 得自己加**：后端这个端点是 Requires 登录的，
 * 漏掉 Authorization 就是那句 401「登录态已失效」——而且看起来像"登录坏了"，
 * 其实只是这一个请求没带头。Content-Type 交给 fetch 自己带（multipart 的
 * boundary 只有它知道），别手写。
 */
export async function uploadPdf(source: PickedFile, title: string): Promise<Book> {
  const form = new FormData();
  form.append('file', source.file, source.name);
  form.append('title', title);

  const send = () => {
    const token = getAccessToken();
    return fetch(`${BASE_URL}/books/pdf`, {
      method: 'POST',
      body: form,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
  };

  let response = await send();
  // 与 request() 一致：access token 只有 15 分钟，撞上过期先静默续期再重放一次
  // （FormData 可以重复发，不像流那样发过就废）
  if (response.status === 401) {
    const fresh = await refreshAccessToken().catch(() => null);
    if (fresh) response = await send();
  }
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
