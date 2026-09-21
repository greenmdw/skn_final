import type { Api } from '../types'
import { auth } from './auth'
import { chat } from './chat'
import { checks } from './checks'
import { plans } from './plans'
import { setups } from './setups'

export const mockApi: Api = { auth, chat, plans, checks, setups }
