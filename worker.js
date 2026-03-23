/**
 * Cloudflare Worker для обработки заявок с сайта AdsPay BY
 * Отправляет уведомления напрямую в Telegram менеджеру
 */

// BOT_TOKEN и MANAGER_CHAT_ID задаются через переменные окружения Cloudflare.
// BOT_TOKEN — секрет (wrangler secret put BOT_TOKEN).
// MANAGER_CHAT_ID задаётся в wrangler.toml [vars] или через Dashboard.

const MINSK_UTC_OFFSET_HOURS = 3; // UTC+3 (Минск)

export default {
  async fetch(request, env, ctx) {
    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type',
        },
      });
    }

    // Только POST запросы
    if (request.method !== 'POST') {
      return new Response('Method not allowed', {
        status: 405,
        headers: {
          'Access-Control-Allow-Origin': '*',
        },
      });
    }

    try {
      const data = await request.json();

      // Валидация данных
      if (!data.name || !data.telegram) {
        return new Response(
          JSON.stringify({
            success: false,
            error: 'Имя и Telegram обязательны',
          }),
          {
            status: 400,
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
            },
          }
        );
      }

      // Форматирование платформ
      const platforms = Array.isArray(data.platforms)
        ? data.platforms.join(', ')
        : (data.platforms || 'не указаны');

      // Форматирование времени (Минск UTC+3)
      const now = new Date();
      const minskTime = new Date(now.getTime() + (MINSK_UTC_OFFSET_HOURS * 60 * 60 * 1000));
      const timeString = minskTime.toISOString().slice(0, 19).replace('T', ' ');

      // Красивое сообщение для Telegram
      const message = `
📝 <b>НОВАЯ ЗАЯВКА С САЙТА</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━

👤 <b>Имя:</b> ${escapeHtml(data.name)}
📱 <b>Telegram:</b> ${escapeHtml(data.telegram)}
💼 <b>Платформы:</b> ${escapeHtml(platforms)}
💰 <b>Бюджет:</b> ${escapeHtml(data.budget || 'не указан')}
💬 <b>Комментарий:</b> ${escapeHtml(data.comment || '—')}

🌐 <b>Источник:</b> ${escapeHtml(data.source || 'website_form')}
🕐 <b>Время (Минск):</b> ${timeString}
      `.trim();

      // Токен и chat_id берутся из переменных окружения
      const botToken = env.BOT_TOKEN;
      if (!botToken) {
        console.error('BOT_TOKEN is not set');
        throw new Error('Bot token is not configured');
      }

      const managerChatId = env.MANAGER_CHAT_ID;

      // Отправка в Telegram
      const telegramUrl = `https://api.telegram.org/bot${botToken}/sendMessage`;

      const telegramResponse = await fetch(telegramUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          chat_id: managerChatId,
          text: message,
          parse_mode: 'HTML',
        }),
      });

      const telegramData = await telegramResponse.json();

      if (!telegramResponse.ok) {
        console.error('Telegram API error:', telegramData);
        throw new Error(`Telegram API error: ${telegramData.description || 'Unknown error'}`);
      }

      // Успешный ответ
      return new Response(
        JSON.stringify({
          success: true,
          message: 'Заявка успешно отправлена',
        }),
        {
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
          },
        }
      );

    } catch (error) {
      console.error('Worker error:', error);

      return new Response(
        JSON.stringify({
          success: false,
          error: 'Ошибка отправки. Напишите напрямую в Telegram: https://t.me/tvoy_rot_naoborot_rb',
        }),
        {
          status: 500,
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
          },
        }
      );
    }
  },
};

/**
 * Экранирование HTML для безопасности
 */
function escapeHtml(text) {
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  };
  return String(text).replace(/[&<>"']/g, m => map[m]);
}
