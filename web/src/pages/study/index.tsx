import { useCallback, useEffect, useState } from 'react';
import { Text, View } from '@tarojs/components';
import Taro, { useDidShow, useRouter } from '@tarojs/taro';
import { Button } from '@nutui/nutui-react-taro';

import { Markdown } from '../../components/Markdown';
import { QuestionCard } from '../../components/QuestionCard';
import { useRequireAuth } from '../../components/RequireAuth';
import { api } from '../../services/api';
import { errorText } from '../../services/request';
import type { Attempt, DayDetail } from '../../models/types';
import './index.less';

const POLL_INTERVAL = 2000;

/** 有任务在后台跑（讲解/出题/批改）就得继续轮询。 */
function needsPolling(day: DayDetail): boolean {
  return (
    day.lesson?.status === 'running' ||
    day.quiz_status === 'running' ||
    day.attempts.some((a) => a.status === 'running')
  );
}

function latestAttempt(attempts: Attempt[], questionId: number): Attempt | undefined {
  const mine = attempts.filter((a) => a.question_id === questionId);
  return mine[mine.length - 1];
}

export default function Study() {
  useRequireAuth();
  const router = useRouter();
  const dayId = Number(router.params.dayId);
  const [day, setDay] = useState<DayDetail | null>(null);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [starting, setStarting] = useState(false);

  const load = useCallback(async () => {
    try {
      setDay(await api.getDay(dayId));
    } catch (error) {
      Taro.showToast({ title: errorText(error), icon: 'none' });
    }
  }, [dayId]);

  useDidShow(() => {
    if (dayId) load();
  });

  // 每次拉完，只要还有任务在跑就再排一次。依赖里带 day 是为了让每轮拉取
  // 都能重新判断一次，而不是只在挂载时判断。
  const polling = day ? needsPolling(day) : false;
  useEffect(() => {
    if (!polling) return;
    const timer = setTimeout(load, POLL_INTERVAL);
    return () => clearTimeout(timer);
  }, [polling, day, load]);

  const run = async (action: () => Promise<DayDetail>, label: string) => {
    setStarting(true);
    try {
      setDay(await action());
    } catch (error) {
      Taro.showToast({ title: `${label}失败：${errorText(error)}`, icon: 'none' });
    } finally {
      setStarting(false);
    }
  };

  const onSubmitAnswer = async (questionId: number, answer: string) => {
    try {
      await api.submitAnswer(questionId, answer);
      await load();
    } catch (error) {
      Taro.showToast({ title: errorText(error), icon: 'none' });
    }
  };

  const onComplete = async () => {
    try {
      await api.completeDay(dayId);
      Taro.showToast({ title: '今天学完了', icon: 'success' });
      await load();
    } catch (error) {
      Taro.showToast({ title: errorText(error), icon: 'none' });
    }
  };

  if (!day) {
    return (
      <View className="page">
        <View className="empty">
          <Text>加载中…</Text>
        </View>
      </View>
    );
  }

  const lesson = day.lesson;
  const lessonRunning = lesson?.status === 'running';
  const lessonDone = lesson?.status === 'done' && Boolean(lesson.content);

  return (
    <View className="page">
      <View className="card">
        <Text className="day-index">第 {day.day_index} 天</Text>
        <Text className="day-title">{day.title}</Text>
        <Text className="muted">
          {day.char_count} 字 · {day.sections.length} 节
        </Text>

        {day.concepts.length ? (
          <View className="concepts">
            {day.concepts.map((concept) => (
              <Text key={concept.id} className="concept">
                {concept.name}
              </Text>
            ))}
          </View>
        ) : null}

        <View className="source-toggle" onClick={() => setSourceOpen(!sourceOpen)}>
          <Text>{sourceOpen ? '收起原文' : '看原文'}</Text>
        </View>

        {sourceOpen ? (
          <View className="source">
            {day.sections.map((section) => (
              <View key={section.id} className="source-section">
                {section.title ? <Text className="source-title">{section.title}</Text> : null}
                <Text className="prose">{section.content}</Text>
              </View>
            ))}
          </View>
        ) : null}
      </View>

      <View className="card">
        <Text className="card-title">AI 讲解</Text>

        {!lesson ? (
          <Button
            type="primary"
            block
            loading={starting}
            onClick={() => run(() => api.startLesson(dayId), '生成讲解')}
          >
            生成讲解
          </Button>
        ) : null}

        {lessonRunning ? <Text className="muted">正在备课，通常十几秒到一分钟…</Text> : null}

        {lesson?.status === 'failed' ? (
          <View>
            <Text className="error">{lesson.error || '生成失败了'}</Text>
            <View className="retry">
              <Button block onClick={() => run(() => api.startLesson(dayId), '重试')}>
                重试
              </Button>
            </View>
          </View>
        ) : null}

        {lessonDone ? <Markdown source={lesson.content as string} /> : null}
      </View>

      {lessonDone ? (
        <View className="card">
          <View className="row">
            <Text className="card-title">自测</Text>
            {day.quiz_status === 'running' ? <Text className="muted">出题中…</Text> : null}
          </View>

          {day.questions.length === 0 && day.quiz_status !== 'running' ? (
            <Button
              type="primary"
              block
              loading={starting}
              onClick={() => run(() => api.startQuiz(dayId), '出题')}
            >
              出题
            </Button>
          ) : null}

          {day.quiz_error ? <Text className="error">{day.quiz_error}</Text> : null}

          {day.questions.map((question, index) => (
            <QuestionCard
              key={question.id}
              index={index}
              question={question}
              attempt={latestAttempt(day.attempts, question.id)}
              onSubmit={onSubmitAnswer}
            />
          ))}
        </View>
      ) : null}

      <View className="footer">
        {day.status === 'done' ? (
          <Button
            block
            onClick={async () => {
              await api.reopenDay(dayId);
              await load();
            }}
          >
            重新打开这一天
          </Button>
        ) : (
          <Button type="primary" block onClick={onComplete}>
            标记今天学完
          </Button>
        )}
      </View>
    </View>
  );
}
