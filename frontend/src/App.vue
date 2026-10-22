<script setup lang="ts">
import { theme } from "ant-design-vue";
import zhCN from "ant-design-vue/es/locale/zh_CN";
import dayjs from "dayjs";
import "dayjs/locale/zh-cn";
import { useRoute } from "vue-router";
import AppIcon from "@/components/AppIcon.vue";
import ChatAssistant from "@/components/ChatAssistant.vue";
import "./styles.css";
const route = useRoute();
dayjs.locale("zh-cn");
const appTheme = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: "#184c3c",
    colorText: "#1f2925",
    colorTextSecondary: "#747c85",
    colorBorder: "#d8dedb",
    borderRadius: 8,
    fontFamily:
      'Inter, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    controlHeightLG: 46,
    fontSize: 15,
  },
};
</script>
<template>
  <a-config-provider :theme="appTheme" :locale="zhCN"
    ><div class="app-shell">
      <a class="skip-link" href="#main-content">跳转到主要内容</a>
      <header class="site-header">
        <div class="header-inner">
          <router-link
            to="/"
            class="brand"
            aria-label="HelloAgents 旅行规划首页"
            ><AppIcon name="compass" :size="39" /><span class="brand-name"
              >HelloAgents</span
            ><span class="brand-caption">旅行规划</span></router-link
          >
          <nav class="primary-nav" aria-label="主导航">
            <router-link
              to="/"
              :aria-current="route.path === '/' ? 'page' : undefined"
              >规划行程</router-link
            ><router-link
              to="/result"
              :aria-current="route.path === '/result' ? 'page' : undefined"
              >我的行程</router-link
            >
          </nav>
        </div>
      </header>
      <main
        id="main-content"
        class="page-container"
        :class="{ 'result-container': route.path === '/result' }"
      >
        <router-view />
      </main>
      <ChatAssistant />
      <footer class="site-footer">HelloAgents · 智能旅行规划</footer>
    </div></a-config-provider
  >
</template>
