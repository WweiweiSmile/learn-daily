import { useEffect, useState } from 'react';
import { Text, Textarea, View } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { Button } from '@nutui/nutui-react-taro';

import { Markdown } from './Markdown';
import type { Attempt, Question } from '../models/types';
import './QuestionCard.less';

const VERDICT_TEXT: Record<string, string> = {
  correct: '答对了',
  partial: '部分正确',
  off: '偏离了',
};

interface Props {
  index: number;
  question: Question;
  attempt?: Attempt;
  onSubmit: (questionId: number, answer: string) => Promise<void>;
}

export function QuestionCard({ index, question, attempt, onSubmit }: Props) {
  const [draft, setDraft] = useState('');
  const [submitting, setSubmitting] = useState(false);
  // 批改完还能再答一次。读完反馈回头重答，是这套东西最有价值的用法之一——
  // 所以不能答完就把输入框锁死。
  const [retrying, setRetrying] = useState(false);

  // 换了题就把草稿和重答状态清掉，不然会串到下一题
  useEffect(() => {
    setDraft('');
    setRetrying(false);
  }, [question.id]);

  const grading = attempt?.status === 'running';
  const graded = attempt?.status === 'done';
  const answering = !graded || retrying;

  const submit = async (answer: string) => {
    if (!answer.trim()) {
      Taro.showToast({ title: '先写点东西再交', icon: 'none' });
      return;
    }
    setSubmitting(true);
    try {
      await onSubmit(question.id, answer);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View className="q">
      <View className="q-head">
        <Text className="q-index">第 {index + 1} 题</Text>
        <Text className="q-kind">{question.kind === 'single' ? '单选' : '简答'}</Text>
      </View>

      <Text className="q-stem">{question.stem}</Text>

      {question.kind === 'single' ? (
        <View className="q-options">
          {question.options.map((option) => (
            <View
              key={option}
              className={`q-option ${draft === option ? 'q-option-on' : ''}`}
              onClick={() => answering && setDraft(option)}
            >
              <Text>{option}</Text>
            </View>
          ))}
        </View>
      ) : answering ? (
        <Textarea
          className="q-input"
          value={draft}
          disabled={grading}
          maxlength={-1}
          placeholder="用自己的话写，不用抄原文"
          onInput={(e) => setDraft(e.detail.value)}
        />
      ) : null}

      {answering && !grading ? (
        <Button type="primary" size="small" loading={submitting} onClick={() => submit(draft)}>
          提交
        </Button>
      ) : null}

      {graded && !retrying ? (
        <View className="q-again">
          <Button size="small" onClick={() => setRetrying(true)}>
            再答一次
          </Button>
        </View>
      ) : null}

      {grading ? (
        <View className="q-grading">
          <Text className="muted">老师正在批改…</Text>
        </View>
      ) : null}

      {graded && attempt ? (
        <View className="q-result">
          <View className="q-verdict-row">
            <Text className={`q-verdict q-verdict-${attempt.verdict}`}>
              {VERDICT_TEXT[attempt.verdict || ''] || '已批改'}
            </Text>
            <Text className="q-score">{attempt.score} 分</Text>
          </View>

          {/* 简答也要把自己写的显示出来——不然没法跟参考答案逐点对照 */}
          <View className="q-block q-block-answer">
            <Text className="q-block-title">你的答案</Text>
            <Text className="prose">{attempt.user_answer || '（没有作答）'}</Text>
          </View>

          {attempt.answer_key ? (
            <View className="q-block q-block-key">
              <Text className="q-block-title">参考答案</Text>
              <Text className="prose">{attempt.answer_key}</Text>
            </View>
          ) : null}

          {attempt.got_right.length ? (
            <View className="q-block q-block-good">
              <Text className="q-block-title">答对的</Text>
              {attempt.got_right.map((item, i) => (
                <Text key={i} className="q-item">
                  ＋ {item}
                </Text>
              ))}
            </View>
          ) : null}

          {attempt.got_wrong.length ? (
            <View className="q-block q-block-bad">
              <Text className="q-block-title">答错或漏掉的</Text>
              {attempt.got_wrong.map((item, i) => (
                <Text key={i} className="q-item">
                  － {item}
                </Text>
              ))}
            </View>
          ) : null}

          {attempt.guidance ? (
            <View className="q-block">
              <Text className="q-block-title">老师怎么讲</Text>
              <Markdown source={attempt.guidance} />
            </View>
          ) : null}

          {attempt.takeaway ? (
            <View className="q-block q-block-takeaway">
              <Text className="prose">一句话：{attempt.takeaway}</Text>
            </View>
          ) : null}

          {attempt.concept ? (
            <Text className="muted">这道题考查：{attempt.concept}</Text>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}
