import { dolcevitahubScenario } from './dolcevitahub.mjs';
import { defaultShopifyScenario } from './default-shopify.mjs';

const scenarios = [dolcevitahubScenario, defaultShopifyScenario];

export function resolveScenario(baseUrl, forcedScenarioId = '') {
  const forced = String(forcedScenarioId || '').trim();
  if (forced) {
    const byId = scenarios.find((item) => item.id === forced);
    if (!byId) {
      throw new Error(`Unknown scenario id: ${forced}`);
    }
    return byId;
  }

  const matched = scenarios.find((item) => item.matches(baseUrl));
  if (!matched) {
    throw new Error('No scenario matched');
  }
  return matched;
}

export function listScenarioIds() {
  return scenarios.map((item) => item.id);
}
