import type { Material } from '../api/types';

/** 上传台接受的格式，与 TextIn xParse 的能力对齐 */
export const MATERIAL_ACCEPT =
  '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.png,.jpg,.jpeg,.txt,.ofd,.csv,.md';

const SUPPORTED_SUFFIXES = MATERIAL_ACCEPT.split(',');

/** 拖拽不受 accept 限制，所以进上传前先自己挡一道，省一次注定失败的上传 */
export function isSupportedFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return SUPPORTED_SUFFIXES.some((suffix) => name.endsWith(suffix));
}

export const MATERIAL_TYPE_LABEL: Record<string, string> = {
  rfp: '招标 / 需求文件',
  minutes: '会议纪要',
  qa: '答疑纪要',
  email: '往来邮件',
  chat: '聊天记录',
  other: '其他材料',
};

/** 材料类型以上传时的判定为准；类型不明确时再按文件名兜底（老数据、粘贴进来的文字） */
export function materialType(material: Material): string {
  if (material.material_type && material.material_type !== 'other') return material.material_type;
  const name = material.filename;
  if (name.includes('聊天') || name.includes('微信')) return 'chat';
  if (name.includes('邮件')) return 'email';
  return material.material_type || 'other';
}

export function materialStatusLabel(status: Material['status']): string {
  if (status === 'parsed') return '已读取';
  if (status === 'failed') return '读取失败';
  return '读取中';
}

/** 还读完的材料：上传 / 解析中。这两个状态对用户是同一件事。 */
export function isMaterialPending(status: Material['status']): boolean {
  return status === 'uploaded' || status === 'parsing';
}
