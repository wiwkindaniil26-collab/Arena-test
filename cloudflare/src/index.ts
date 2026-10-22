/**
 * Cloudflare Containers: Worker принимает апдейты Telegram и проксирует их
 * в Docker-контейнер, где работает aiogram в webhook-режиме.
 *
 * Почему не Workers напрямую: боту нужен Python, ffmpeg и файловая система,
 * а polling в Workers невозможен в принципе. Контейнер это решает, Worker
 * остаётся тонким прокси и одновременно «будильником» для контейнера.
 */

import { DurableObject } from "cloudflare:workers";

interface Env {
  MUSIC_BOT: DurableObjectNamespace<MusicBotContainer>;
  /** wrangler secret put BOT_TOKEN */
  BOT_TOKEN: string;
  /** wrangler secret put WEBHOOK_SECRET — Telegram присылает его в заголовке */
  WEBHOOK_SECRET?: string;
  /** необязательно: "111,222" — закрытый режим */
  ALLOWED_USERS?: string;
  /** необязательно: содержимое cookies.txt (Netscape) для источников с логином */
  COOKIES_CONTENT?: string;
  LOG_LEVEL?: string;
}

/** Порт, который слушает python-процесс внутри контейнера. */
const PORT = 8080;

/**
 * Через сколько бездействия контейнер засыпает (холодный старт ~3–8 секунд).
 * Больше значение = библиотека живёт дольше, но и счёт за память выше.
 */
const IDLE_TIMEOUT_MS = 10 * 60 * 1000;

/** Размер инстанса: ffmpeg любит память, поэтому не lite. */
const INSTANCE = "basic";

export class MusicBotContainer extends DurableObject<Env> {
  #starting?: Promise<void>;
  #publicUrl?: string;

  async fetch(request: Request): Promise<Response> {
    // origin первого запроса = публичный адрес воркера:
    // его же отдаём Telegram как URL вебхука
    this.#publicUrl ??= new URL(request.url).origin;

    this.#starting ??= this.#start().finally(() => {
      this.#starting = undefined;
    });
    await this.#starting;

    // контейнер ждёт обычный HTTP-запрос на свой порт
    const url = new URL(request.url);
    url.protocol = "http:";
    url.host = "container";
    const forwarded = new Request(url, request);
    forwarded.headers.delete("host");

    return this.ctx.container!.getTcpPort(PORT).fetch(forwarded);
  }

  async #start(): Promise<void> {
    const container = this.ctx.container!;

    if (!container.running) {
      if (!this.env.BOT_TOKEN) {
        throw new Error(
          "Секрет BOT_TOKEN не задан: npx wrangler secret put BOT_TOKEN",
        );
      }

      const env: Record<string, string> = {
        RUN_MODE: "webhook",
        PORT: String(PORT),
        BOT_TOKEN: this.env.BOT_TOKEN,
        WEBHOOK_BASE_URL: this.#publicUrl ?? "",
        ALLOWED_USERS: this.env.ALLOWED_USERS ?? "",
        LOG_LEVEL: this.env.LOG_LEVEL ?? "INFO",
      };
      if (this.env.WEBHOOK_SECRET) {
        env.WEBHOOK_SECRET = this.env.WEBHOOK_SECRET;
      }
      if (this.env.COOKIES_CONTENT) {
        env.COOKIES_CONTENT = this.env.COOKIES_CONTENT;
      }

      container.start({
        image: container.images.bot,
        instance: INSTANCE,
        // без этого yt-dlp не достучится до Telegram и источников музыки
        enableInternet: true,
        env,
      });
    }

    await container.setInactivityTimeout(IDLE_TIMEOUT_MS);

    // ждём /health, иначе Telegram получит ошибку на первом апдейте
    let lastError: unknown;
    for (let attempt = 0; attempt < 60; attempt++) {
      try {
        const response = await container.getTcpPort(PORT).fetch(
          "http://container/health",
          { signal: AbortSignal.timeout(1000) },
        );
        await response.body?.cancel();
        if (response.ok) {
          return;
        }
        lastError = new Error(`/health вернул ${response.status}`);
      } catch (error) {
        lastError = error;
      }
      await scheduler.wait(500);
    }

    throw new Error("Контейнер не поднялся на порту 8080", {
      cause: lastError,
    });
  }
}

const worker: ExportedHandler<Env> = {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Заход на «/» в браузере поднимает контейнер, и бот регистрирует вебхук
    // в Telegram. Это же — способ «разбудить» бота после деплоя.
    if (url.pathname === "/" && request.method === "GET") {
      try {
        const health = new URL("/health", url);
        const response = await env.MUSIC_BOT.getByName("main").fetch(
          new Request(health, { method: "GET" }),
        );
        const ready = response.ok;
        return new Response(
          ready
            ? "tg-music-bot: контейнер работает, вебхук зарегистрирован ✅\n"
            : `tg-music-bot: контейнер ответил ${response.status} ⚠️\n`,
          { headers: { "content-type": "text/plain; charset=utf-8" } },
        );
      } catch (error) {
        return new Response(`tg-music-bot: контейнер не поднялся: ${String(error)}\n`, {
          status: 500,
          headers: { "content-type": "text/plain; charset=utf-8" },
        });
      }
    }

    // один экземпляр: все апдейты одному контейнеру (вебхук у бота один)
    return env.MUSIC_BOT.getByName("main").fetch(request);
  },

  // Keep-alive по расписанию: включи cron в wrangler.toml, если хочешь,
  // чтобы контейнер не засыпал и библиотека жила дольше.
  async scheduled(_controller: ScheduledController, env: Env): Promise<void> {
    await env.MUSIC_BOT.getByName("main").fetch(
      new Request("https://keep-alive.local/health"),
    );
  },
};

export default worker;
