import { useCallback, useState } from 'react';
import { Text, Textarea, View } from '@tarojs/components';
import Taro, { useDidShow } from '@tarojs/taro';
import { Button, Popup } from '@nutui/nutui-react-taro';

import { api, pickPdf, uploadPdf } from '../../services/api';
import { errorText } from '../../services/request';
import { useRequireAuth } from '../../components/RequireAuth';
import { globalLogout } from '../../utils/sso';
import type { Book } from '../../models/types';
import './index.less';

export default function Library() {
  useRequireAuth();
  const [books, setBooks] = useState<Book[]>([]);
  const [busy, setBusy] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteTitle, setPasteTitle] = useState('');
  const [pasteText, setPasteText] = useState('');

  const load = useCallback(async () => {
    try {
      setBooks(await api.listBooks());
    } catch (error) {
      Taro.showToast({ title: errorText(error), icon: 'none' });
    }
  }, []);

  useDidShow(() => {
    load();
  });

  const onUploadPdf = async () => {
    if (busy) return;
    let picked;
    try {
      picked = await pickPdf();
    } catch (error) {
      Taro.showToast({ title: errorText(error), icon: 'none' });
      return;
    }
    if (!picked) return; // 用户取消

    setBusy(true);
    Taro.showLoading({ title: '解析中…', mask: true });
    try {
      const book = await uploadPdf(picked, '');
      Taro.hideLoading();
      if (book.status === 'failed') {
        // 扫描版 PDF 走的就是这条路：要当面说清为什么读不了，不能只转个圈
        Taro.showModal({ title: '这本书读不了', content: book.error || '解析失败', showCancel: false });
      } else {
        Taro.showToast({ title: `切成 ${book.day_count} 天`, icon: 'success' });
      }
      load();
    } catch (error) {
      Taro.hideLoading();
      Taro.showToast({ title: errorText(error), icon: 'none' });
    } finally {
      setBusy(false);
    }
  };

  const onPasteSubmit = async () => {
    if (!pasteText.trim()) {
      Taro.showToast({ title: '文本是空的', icon: 'none' });
      return;
    }
    setBusy(true);
    try {
      const book = await api.createTextBook(pasteTitle.trim(), pasteText);
      setPasteOpen(false);
      setPasteTitle('');
      setPasteText('');
      Taro.showToast({ title: `切成 ${book.day_count} 天`, icon: 'success' });
      load();
    } catch (error) {
      Taro.showToast({ title: errorText(error), icon: 'none' });
    } finally {
      setBusy(false);
    }
  };

  const onDelete = (book: Book) => {
    Taro.showModal({
      title: '删除这本书',
      content: `《${book.title}》的学习记录会一起删掉。`,
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await api.deleteBook(book.id);
          load();
        } catch (error) {
          Taro.showToast({ title: errorText(error), icon: 'none' });
        }
      },
    });
  };

  const openBook = (book: Book) => {
    Taro.navigateTo({ url: `/pages/book/index?id=${book.id}` });
  };

  const onLogout = () => {
    Taro.showModal({
      title: '退出登录',
      content: '确定要退出吗？',
      success: (res) => {
        if (!res.confirm) return;

        // 全局退出：清本地 + 整页跳认证中心的 `/logout`，由它吊销该用户
        // **全部应用**的登录态（含 call-front）。
        //
        // 不能只清本地就完事 —— 认证域那个会话 cookie 前端删不掉，
        // 清了本地守卫会立刻再跳一次 /sso，人又被静默登回来。
        globalLogout();
      },
    });
  };

  return (
    <View className="page">
      <View className="row header">
        <Text className="header-title">我的书架</Text>
        <View className="header-actions">
          <Text
            className="header-action"
            onClick={() => Taro.navigateTo({ url: '/pages/diagnosis/index' })}
          >
            诊断
          </Text>
          <Text className="header-action" data-testid="btn-logout" onClick={onLogout}>
            退出
          </Text>
        </View>
      </View>

      <View className="actions">
        <Button type="primary" size="small" onClick={onUploadPdf} loading={busy}>
          上传 PDF
        </Button>
        <Button size="small" onClick={() => setPasteOpen(true)}>
          粘贴文本
        </Button>
      </View>

      {books.length === 0 ? (
        <View className="empty">
          <Text>书架还是空的。传一本书进来，或者先粘一段文字试试。</Text>
        </View>
      ) : (
        books.map((book) => (
          <View key={book.id} className="card book" onClick={() => openBook(book)}>
            <View className="row">
              <Text className="book-title">{book.title}</Text>
              <Text className="delete" onClick={() => onDelete(book)}>
                删除
              </Text>
            </View>

            <Text className="muted">
              {book.day_count} 天 · 约 {book.total_chars} 字
            </Text>

            <View className="progress">
              <View
                className="progress-fill"
                style={{
                  width: `${book.day_count ? (book.completed_days / book.day_count) * 100 : 0}%`,
                }}
              />
            </View>
            <Text className="muted">
              已学完 {book.completed_days}/{book.day_count} 天
            </Text>

            {book.error ? <Text className="book-error">{book.error}</Text> : null}
            {book.warning ? <Text className="book-warning">{book.warning}</Text> : null}
          </View>
        ))
      )}

      <Popup
        visible={pasteOpen}
        position="bottom"
        round
        onClose={() => setPasteOpen(false)}
        style={{ height: '70%', padding: '16px' }}
      >
        <View className="paste">
          <Text className="card-title">粘贴文本</Text>
          <Textarea
            className="paste-title"
            value={pasteTitle}
            maxlength={-1}
            placeholder="标题（可留空）"
            onInput={(e) => setPasteTitle(e.detail.value)}
          />
          {/* maxlength 必须显式给 -1：Taro 的 Textarea 默认只让输入 140 个字，
              粘一篇长文会被悄悄截断，而且截断还是静默的。 */}
          <Textarea
            className="paste-body"
            value={pasteText}
            maxlength={-1}
            placeholder="把要学的内容粘在这里。有 Markdown 标题（# 一级、## 二级）就会按标题分章节。"
            onInput={(e) => setPasteText(e.detail.value)}
          />
          <Button type="primary" block loading={busy} onClick={onPasteSubmit}>
            开始切分
          </Button>
        </View>
      </Popup>
    </View>
  );
}
