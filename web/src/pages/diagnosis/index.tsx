import { useCallback, useEffect, useState } from 'react';
import { Text, View } from '@tarojs/components';
import Taro, { useDidShow, useRouter } from '@tarojs/taro';
import { Button } from '@nutui/nutui-react-taro';

import { api } from '../../services/api';
import { errorText } from '../../services/request';
import { useRequireAuth } from '../../components/RequireAuth';
import type { Diagnosis } from '../../models/types';
import './index.less';

const POLL_INTERVAL = 2000;

export default function DiagnosisPage() {
  useRequireAuth();
  const router = useRouter();
  const bookId = router.params.bookId ? Number(router.params.bookId) : undefined;
  const [data, setData] = useState<Diagnosis | null>(null);
  const [starting, setStarting] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.getDiagnosis(bookId));
    } catch (error) {
      Taro.showToast({ title: errorText(error), icon: 'none' });
    }
  }, [bookId]);

  useDidShow(() => {
    load();
  });

  const running = data?.status === 'running';
  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(load, POLL_INTERVAL);
    return () => clearTimeout(timer);
  }, [running, data, load]);

  const start = async () => {
    setStarting(true);
    try {
      setData(await api.startDiagnosis(bookId));
    } catch (error) {
      Taro.showToast({ title: errorText(error), icon: 'none' });
    } finally {
      setStarting(false);
    }
  };

  if (!data) {
    return (
      <View className="page">
        <View className="empty">
          <Text>加载中…</Text>
        </View>
      </View>
    );
  }

  const result = data.result;
  const hasEvidence = data.evidence.graded > 0;

  return (
    <View className="page">
      <View className="card">
        <Text className="card-title">{bookId == null ? '全部书目' : '这本书'} · 诊断</Text>
        <Text className="muted">
          依据：{data.evidence.concepts} 个概念 · {data.evidence.graded} 次作答 ·{' '}
          {data.evidence.misconceptions} 条错题
        </Text>

        {!hasEvidence ? (
          <Text className="hint">
            还没有作答记录，诊断会无从下手。先去学一天、答一道题再来。
          </Text>
        ) : null}

        {data.is_stale ? (
          <Text className="stale">又有新的作答了，这份诊断可以重新生成。</Text>
        ) : null}

        {hasEvidence ? (
          <View className="action">
            <Button type="primary" block loading={starting || running} onClick={start}>
              {result ? '重新诊断' : '生成诊断'}
            </Button>
          </View>
        ) : null}

        {running ? <Text className="muted">正在通读你的全部记录…</Text> : null}
        {data.status === 'failed' ? (
          <Text className="error">{data.error || '诊断失败了'}</Text>
        ) : null}
      </View>

      {result ? (
        <>
          <View className="card">
            <Text className="section-title">学到哪了</Text>
            <Text className="prose">{result.summary}</Text>
          </View>

          {result.learned.length ? (
            <View className="card">
              <Text className="section-title">已经建立起来的</Text>
              {result.learned.map((item, index) => (
                <View key={index} className="item item-good">
                  <Text className="item-concept">{item.concept}</Text>
                  <Text className="item-evidence">{item.evidence}</Text>
                </View>
              ))}
            </View>
          ) : null}

          {result.gaps.length ? (
            <View className="card">
              <Text className="section-title">还差什么</Text>
              {result.gaps.map((item, index) => (
                <View key={index} className="item item-bad">
                  <Text className="item-concept">{item.concept}</Text>
                  <Text className="item-evidence">{item.evidence}</Text>
                  {item.suggestion ? (
                    <Text className="item-suggestion">→ {item.suggestion}</Text>
                  ) : null}
                </View>
              ))}
            </View>
          ) : null}

          {result.blind_spots.length ? (
            <View className="card">
              <Text className="section-title">盲区</Text>
              <Text className="muted">
                这些概念你学过，但从来没被检验过——比答错更值得警惕。
              </Text>
              <View className="chips">
                {result.blind_spots.map((name, index) => (
                  <Text key={index} className="chip">
                    {name}
                  </Text>
                ))}
              </View>
            </View>
          ) : null}

          {result.pattern ? (
            <View className="card">
              <Text className="section-title">反复出现的模式</Text>
              <Text className="prose">{result.pattern}</Text>
            </View>
          ) : null}

          {result.next_steps.length ? (
            <View className="card">
              <Text className="section-title">接下来做什么</Text>
              {result.next_steps.map((step, index) => (
                <Text key={index} className="step">
                  {index + 1}. {step}
                </Text>
              ))}
            </View>
          ) : null}
        </>
      ) : null}
    </View>
  );
}
