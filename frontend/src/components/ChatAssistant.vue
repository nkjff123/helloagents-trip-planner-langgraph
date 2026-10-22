<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { streamChatMessage } from '@/services/api'
import { readTripPlan } from '@/utils/trip'
import AppIcon from '@/components/AppIcon.vue'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  isStreaming?: boolean
  toolStatus?: string
}

const isOpen = ref(false)
const inputMessage = ref('')
const isGenerating = ref(false)
const conversationId = ref(`conv_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`)
const messagesContainer = ref<HTMLDivElement | null>(null)
let abortController: AbortController | null = null

const quickPrompts = [
  '跟团游被强制购物如何维权？',
  '酒店线上预订被临时取消怎么办？',
  '高山徒步发生失温有哪些自救常识？',
  '景区导游讲解服务有哪些行业规范？',
]

// 读取当前行程上下文
const currentTrip = computed(() => {
  try {
    const raw = typeof window !== 'undefined' ? sessionStorage.getItem('trip_plan') : null
    const plan = readTripPlan(raw)
    if (plan && plan.city) {
      const poiNames: string[] = []
      plan.days?.forEach((d) => {
        d.attractions?.forEach((a) => {
          if (a.name) poiNames.push(a.name)
        })
      })
      return {
        destination: plan.city,
        days: plan.days?.length || 1,
        poi_names: poiNames.slice(0, 8),
      }
    }
  } catch {
    // 忽略解析错误
  }
  return null
})

const messages = ref<ChatMessage[]>([
  {
    id: 'welcome',
    role: 'assistant',
    content:
      '您好！我是您的智能旅游顾问。我已接入文化和旅游部官方旅游法规、旅游安全手册、示范合同与服务规范知识库。您可以随时向我咨询行程建议、旅游避坑、维权法规或安全应急常识！',
  },
])

function toggleChat() {
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    scrollToBottom()
  }
}

async function scrollToBottom() {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

function selectQuickPrompt(prompt: string) {
  if (isGenerating.value) return
  inputMessage.value = prompt
  handleSendMessage()
}

async function handleSendMessage() {
  const text = inputMessage.value.trim()
  if (!text || isGenerating.value) return

  const userMsgId = `user_${Date.now()}`
  messages.value.push({
    id: userMsgId,
    role: 'user',
    content: text,
  })
  inputMessage.value = ''
  scrollToBottom()

  const assistantMsgId = `assistant_${Date.now()}`
  const assistantMsg: ChatMessage = {
    id: assistantMsgId,
    role: 'assistant',
    content: '',
    isStreaming: true,
  }
  messages.value.push(assistantMsg)
  isGenerating.value = true
  scrollToBottom()

  abortController = new AbortController()

  try {
    await streamChatMessage(
      text,
      conversationId.value,
      currentTrip.value,
      (event) => {
        if (event.type === 'tool_start') {
          assistantMsg.toolStatus = event.content || '正在查阅旅游知识库...'
          scrollToBottom()
        } else if (event.type === 'token') {
          assistantMsg.toolStatus = undefined
          assistantMsg.content += event.content || ''
          scrollToBottom()
        } else if (event.type === 'error') {
          assistantMsg.toolStatus = undefined
          assistantMsg.content += `\n[提示: ${event.content || '生成出错'}]`
          scrollToBottom()
        } else if (event.type === 'done') {
          assistantMsg.toolStatus = undefined
          assistantMsg.isStreaming = false
          scrollToBottom()
        }
      },
      abortController.signal
    )
  } catch (err: any) {
    if (err.name !== 'AbortError') {
      assistantMsg.content += `\n[网络错误: ${err.message || '请求失败'}]`
    }
  } finally {
    assistantMsg.isStreaming = false
    assistantMsg.toolStatus = undefined
    isGenerating.value = false
    abortController = null
    scrollToBottom()
  }
}

function handleStop() {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
  isGenerating.value = false
}
</script>

<template>
  <div class="chat-assistant-wrapper">
    <!-- 悬浮触发按钮 -->
    <button
      v-if="!isOpen"
      class="chat-trigger-btn"
      aria-label="打开 AI 旅游顾问助手"
      @click="toggleChat"
    >
      <AppIcon name="compass" :size="24" />
      <span class="trigger-label">AI 顾问</span>
      <span class="badge-dot" title="已挂载文旅部官方知识库"></span>
    </button>

    <!-- 对话主面板 -->
    <div v-else class="chat-panel">
      <!-- 头部 -->
      <div class="chat-header">
        <div class="header-info">
          <div class="title-row">
            <AppIcon name="compass" :size="18" />
            <span class="chat-title">AI 旅游顾问</span>
            <span class="rag-tag">官方知识库</span>
          </div>
          <div v-if="currentTrip" class="trip-context-indicator">
            <AppIcon name="pin" :size="12" />
            <span>已关联当前行程: {{ currentTrip.destination }} ({{ currentTrip.days }}天)</span>
          </div>
        </div>
        <button class="close-btn" aria-label="关闭对话面板" @click="toggleChat">
          <AppIcon name="close" :size="18" />
        </button>
      </div>

      <!-- 消息列表 -->
      <div ref="messagesContainer" class="chat-messages">
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="message-row"
          :class="[msg.role]"
        >
          <div class="message-bubble">
            <div v-if="msg.toolStatus" class="tool-status-bubble">
              <span class="tool-spinner"></span>
              <span>{{ msg.toolStatus }}</span>
            </div>
            <div class="bubble-text">{{ msg.content }}</div>
            <span v-if="msg.isStreaming" class="cursor-blink">|</span>
          </div>
        </div>

        <!-- 快捷提问气泡 -->
        <div v-if="messages.length === 1" class="quick-prompts-container">
          <div class="quick-title">常见专业咨询：</div>
          <button
            v-for="(p, idx) in quickPrompts"
            :key="idx"
            class="quick-prompt-chip"
            @click="selectQuickPrompt(p)"
          >
            {{ p }}
          </button>
        </div>
      </div>

      <!-- 输入区域 -->
      <div class="chat-footer">
        <div class="input-wrapper">
          <textarea
            v-model="inputMessage"
            class="chat-textarea"
            placeholder="提问行程规划、避坑建议或维权法规... (Enter 发送)"
            rows="2"
            :disabled="isGenerating"
            @keydown.enter.prevent="handleSendMessage"
          ></textarea>
          <button
            v-if="isGenerating"
            class="action-btn stop-btn"
            title="停止生成"
            @click="handleStop"
          >
            停止
          </button>
          <button
            v-else
            class="action-btn send-btn"
            :disabled="!inputMessage.trim()"
            @click="handleSendMessage"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-assistant-wrapper {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 9999;
}

.chat-trigger-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 18px;
  background-color: #184c3c;
  color: #ffffff;
  border: none;
  border-radius: 30px;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(24, 76, 60, 0.35);
  font-size: 14px;
  font-weight: 600;
  transition: all 0.2s ease;
  position: relative;
}

.chat-trigger-btn:hover {
  background-color: #12382c;
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(24, 76, 60, 0.45);
}

.badge-dot {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 9px;
  height: 9px;
  background-color: #52c41a;
  border: 2px solid #ffffff;
  border-radius: 50%;
}

.chat-panel {
  width: 380px;
  height: 550px;
  max-height: 82vh;
  background-color: #ffffff;
  border-radius: 14px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.16);
  border: 1px solid #d8dedb;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: slideUp 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(20px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.chat-header {
  padding: 12px 16px;
  background-color: #f7faf8;
  border-bottom: 1px solid #e5ebe7;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #184c3c;
}

.chat-title {
  font-size: 15px;
  font-weight: 700;
}

.rag-tag {
  font-size: 11px;
  background-color: #e6f4ea;
  color: #184c3c;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}

.trip-context-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #5c6b63;
}

.close-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: #747c85;
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.close-btn:hover {
  background-color: #e8eee9;
  color: #1f2925;
}

.chat-messages {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  background-color: #fafbfb;
}

.message-row {
  display: flex;
  width: 100%;
}

.message-row.user {
  justify-content: flex-end;
}

.message-row.assistant {
  justify-content: flex-start;
}

.message-bubble {
  max-width: 86%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 13.5px;
  line-height: 1.55;
  word-break: break-word;
  white-space: pre-wrap;
}

.message-row.user .message-bubble {
  background-color: #184c3c;
  color: #ffffff;
  border-bottom-right-radius: 3px;
}

.message-row.assistant .message-bubble {
  background-color: #ffffff;
  color: #1f2925;
  border: 1px solid #e1e7e3;
  border-bottom-left-radius: 3px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}

.tool-status-bubble {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  margin-bottom: 6px;
  background-color: #f0f7f3;
  color: #184c3c;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 500;
}

.tool-spinner {
  width: 10px;
  height: 10px;
  border: 2px solid #184c3c;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.cursor-blink {
  display: inline-block;
  margin-left: 2px;
  animation: blink 1s infinite;
  color: #184c3c;
  font-weight: bold;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.quick-prompts-container {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 6px;
}

.quick-title {
  font-size: 11.5px;
  color: #8c9791;
  margin-bottom: 2px;
}

.quick-prompt-chip {
  text-align: left;
  background-color: #f0f4f2;
  border: 1px solid #d9e3dd;
  color: #274034;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.quick-prompt-chip:hover {
  background-color: #e2ebe5;
  border-color: #b7cdc1;
  color: #184c3c;
}

.chat-footer {
  padding: 10px 12px;
  background-color: #ffffff;
  border-top: 1px solid #e5ebe7;
}

.input-wrapper {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

.chat-textarea {
  flex: 1;
  border: 1px solid #d2ded7;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
  resize: none;
  outline: none;
  font-family: inherit;
  transition: border-color 0.2s;
}

.chat-textarea:focus {
  border-color: #184c3c;
}

.action-btn {
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: background-color 0.2s;
  height: 38px;
}

.send-btn {
  background-color: #184c3c;
  color: #ffffff;
}

.send-btn:hover:not(:disabled) {
  background-color: #12382c;
}

.send-btn:disabled {
  background-color: #b8c4bd;
  cursor: not-allowed;
}

.stop-btn {
  background-color: #d9363e;
  color: #ffffff;
}

.stop-btn:hover {
  background-color: #b3262d;
}
</style>
