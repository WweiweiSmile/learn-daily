import { useCallback, useState } from 'react';
import { Text, View } from '@tarojs/components';
import Taro, { useDidShow, useRouter } from '@tarojs/taro';
import { Button } from '@nutui/nutui-react-taro';

import { api } from '../../services/api';
import { errorText } from '../../services/request';
import { useRequireAuth } from '../../components/RequireAuth';
import type { BookDetail, DaySummary } from '../../models/types';
import './index.less';

function dayStateText(day: DaySummary, isNext: boolean): string {
  if (day.status === 'done') return '已学完';
  if (day.has_lesson) return '讲解已生成';
  if (isNext) return '从这里开始';
  return `${day.char_count} 字`;
}

export default function BookPage() {
  useRequireAuth();
  const router = useRouter();
  const bookId = Number(router.params.id);
  const [detail, setDetail] = useState<BookDetail | null>(null);

  const load = useCallback(async () => {
    try {
      setDetail(await api.getBook(bookId));
    } catch (error) {
      Taro.showToast({ title: errorText(error), icon: 'none' });
    }
  }, [bookId]);

  useDidShow(() => {
    if (bookId) load();
  });

  if (!detail) {
    return (
      <View className="page">
        <View className="empty">
          <Text>加载中…</Text>
        </View>
      </View>
    );
  }

  const { book, days } = detail;
  const done = days.filter((d) => d.status === 'done').length;
  const nextDay = days.find((d) => d.status !== 'done');

  const openDay = (day: DaySummary) => {
    Taro.navigateTo({ url: `/pages/study/index?dayId=${day.id}` });
  };

  return (
    <View className="page">
      <View className="card">
        <Text className="title">{book.title}</Text>
        <Text className="muted">
          共 {book.day_count} 天 · 约 {book.total_chars} 字 · 已学完 {done} 天
        </Text>
        {book.warning ? <Text className="warning">{book.warning}</Text> : null}

        {nextDay ? (
          <View className="continue">
            <Button type="primary" block onClick={() => openDay(nextDay)}>
              继续 第 {nextDay.day_index} 天
            </Button>
          </View>
        ) : null}

        <View className="continue">
          <Button
            block
            onClick={() =>
              Taro.navigateTo({ url: `/pages/diagnosis/index?bookId=${book.id}` })
            }
          >
            看诊断：我学到哪了、还差什么
          </Button>
        </View>
      </View>

      {days.map((day) => (
        <View
          key={day.id}
          className={`card day ${day.status === 'done' ? 'day-done' : ''}`}
          onClick={() => openDay(day)}
        >
          <View className="row">
            <Text className="day-index">第 {day.day_index} 天</Text>
            <Text className={day.status === 'done' ? 'tag-done' : 'tag-pending'}>
              {dayStateText(day, nextDay?.id === day.id)}
            </Text>
          </View>
          <Text className="day-card-title">{day.title}</Text>
          <Text className="muted">
            {day.section_count} 节 · {day.char_count} 字
            {day.question_count ? ` · ${day.question_count} 题` : ''}
          </Text>
        </View>
      ))}
    </View>
  );
}
