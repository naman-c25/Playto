import { useEffect, useRef } from "react";

/**
 * Polls `callback` every `intervalMs` milliseconds while the component is mounted.
 * Fires once immediately on mount (no initial delay).
 *
 * @param {() => void} callback  - async-safe: new poll won't start until previous resolves
 * @param {number} intervalMs    - polling interval in ms (default: 5000)
 * @param {boolean} enabled      - set to false to pause polling
 */
export function usePolling(callback, intervalMs = 5000, enabled = true) {
  const savedCallback = useRef(callback);

  // Keep ref fresh without restarting the interval
  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) return;

    let active = true;

    async function tick() {
      if (active) {
        await savedCallback.current();
      }
    }

    tick(); // fire immediately
    const id = setInterval(tick, intervalMs);

    return () => {
      active = false;
      clearInterval(id);
    };
  }, [intervalMs, enabled]);
}
