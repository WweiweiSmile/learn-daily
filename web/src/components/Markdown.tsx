import { Text, View } from '@tarojs/components';
import { parseInline, parseMarkdown } from '../utils/markdown';

function inline(text: string) {
  return parseInline(text).map((segment, index) => (
    <Text key={index} className={segment.bold ? 'md-bold' : undefined}>
      {segment.text}
    </Text>
  ));
}

/** 把模型吐出来的 Markdown 渲染成 Taro 组件。块级解析见 utils/markdown.ts。 */
export function Markdown({ source }: { source: string }) {
  const blocks = parseMarkdown(source || '');

  return (
    <View className="md">
      {blocks.map((block, index) => {
        if (block.type === 'heading') {
          return (
            <View key={index} className={`md-h md-h${Math.min(block.level, 4)}`}>
              {block.text}
            </View>
          );
        }
        if (block.type === 'code') {
          return (
            <View key={index} className="md-code">
              <Text>{block.text}</Text>
            </View>
          );
        }
        if (block.type === 'list') {
          return (
            <View key={index} className="md-list">
              {block.items.map((item, itemIndex) => (
                <View key={itemIndex} className="md-li">
                  <Text className="md-marker">{block.ordered ? `${itemIndex + 1}.` : '·'}</Text>
                  <Text className="md-li-text">{inline(item)}</Text>
                </View>
              ))}
            </View>
          );
        }
        return (
          <View key={index} className="md-p">
            {inline(block.text)}
          </View>
        );
      })}
    </View>
  );
}
