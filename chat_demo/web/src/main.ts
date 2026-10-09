import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './styles/theme.css'
import './styles/hljs.css'

createApp(App).use(createPinia()).mount('#app')
