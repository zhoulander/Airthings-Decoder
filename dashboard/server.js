
"use strict";

const https = require("https");
const http = require("http");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");

const AIRTHINGS_API = "http://127.0.0.1:8000";

const PROJECT_DIR = path.resolve(__dirname, "..");
const PUBLIC_DIR = path.join(__dirname, "public");
const DEVICES_FILE = path.join(PROJECT_DIR, "devices.json");
const CONFIG_FILE = path.join(__dirname, "server_config.json");
const QUERY_SCRIPT = path.join(PROJECT_DIR, "QueryWave.py");
const PYTHON = path.join(PROJECT_DIR, ".venv", "bin", "python");

const DEVICE_HEALTH_FILE = path.join(
  __dirname,
  "device_health_history.jsonl"
);

const DEVICE_HEALTH_STATE_FILE = path.join(
  __dirname,
  "device_health_state.json"
);

const DEVICE_HEALTH_RETENTION_DAYS = 30;
const DEVICE_HEALTH_RETENTION_MS =
  DEVICE_HEALTH_RETENTION_DAYS * 24 * 60 * 60 * 1000;

const DEFAULT_CONFIG = {
  port: 3000,
  history_interval_minutes: 180,
  device_connect_delay_seconds: 5,
  outdoor_location: {
    name: "Toronto, Ontario, Canada",
  }
};

let config = load_config();
let job_queue = [];
let active_job = null;
let next_job_id = 1;
let scheduler_timer = null;
let next_history_run = null;
let last_job = null;
let shutting_down = false;

function api_get(endpoint) {
  return new Promise((resolve, reject) => {
    const request = http.get(
      `${AIRTHINGS_API}${endpoint}`,
      response => {
        let body = "";

        response.setEncoding("utf8");

        response.on("data", chunk => {
          body += chunk;
        });

        response.on("end", () => {
          if (
            response.statusCode < 200 ||
            response.statusCode >= 300
          ) {
            return reject(
              new Error(
                `Airthings API returned HTTP ${response.statusCode}: ${body}`
              )
            );
          }

          try {
            resolve(JSON.parse(body));
          } catch {
            reject(
              new Error("Invalid JSON response from Airthings API")
            );
          }
        });
      }
    );

    request.setTimeout(15000, () => {
      request.destroy(
        new Error("Airthings API request timed out")
      );
    });

    request.on("error", reject);
  });
}

async function api_get_all(endpoint) {
  const results = [];
  const limit = 10000;
  let offset = 0;

  while (true) {
    const separator = endpoint.includes("?") ? "&" : "?";

    const data = await api_get(
      `${endpoint}${separator}limit=${limit}&offset=${offset}`
    );

    const records = data.records || data.responses || [];

    results.push(...records);

    if (data.next_offset === null || data.next_offset === undefined) {
      break;
    }

    offset = data.next_offset;
  }

  return results;
}

function load_config() {
  try {
    const saved = JSON.parse(fs.readFileSync(CONFIG_FILE, "utf8"));
    return { ...DEFAULT_CONFIG, ...saved };
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

function save_config() {
  fs.mkdirSync(path.dirname(CONFIG_FILE), { recursive: true });
  const temp = `${CONFIG_FILE}.tmp`;
  fs.writeFileSync(temp, JSON.stringify(config, null, 2));
  fs.renameSync(temp, CONFIG_FILE);
}

// --------------------------------------------------
// Outdoor weather and air quality
// --------------------------------------------------

let outdoor_cache = {
  data: null,
  fetched_at: 0
};

let geocode_cache = new Map();
let last_geocode_request = 0;

function https_json(url, headers = {}) {
  return new Promise((resolve, reject) => {
    const request = https.get(url, {
      headers: {
        "Accept": "application/json",
        ...headers
      }
    }, response => {
      let body = "";

      response.setEncoding("utf8");
      response.on("data", chunk => body += chunk);

      response.on("end", () => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          return reject(
            new Error(`External API returned HTTP ${response.statusCode}`)
          );
        }

        try {
          resolve(JSON.parse(body));
        } catch {
          reject(new Error("Invalid response from external API"));
        }
      });
    });

    request.setTimeout(15000, () => {
      request.destroy(new Error("External API request timed out"));
    });

    request.on("error", reject);
  });
}

function valid_coordinates(latitude, longitude) {
  return Number.isFinite(latitude) &&
    Number.isFinite(longitude) &&
    latitude >= -90 &&
    latitude <= 90 &&
    longitude >= -180 &&
    longitude <= 180;
}

async function search_outdoor_location(query) {
  const term = String(query || "").trim();

  if (term.length < 3 || term.length > 200) {
    throw new Error("Enter at least 3 characters (maximum 200).");
  }

  const cache_key = term.toLowerCase();
  const cached = geocode_cache.get(cache_key);

  if (cached && Date.now() - cached.time < 10 * 60 * 1000) {
    return cached.results;
  }

  // Nominatim public service: maximum one request per second.
  const wait = Math.max(
    0,
    1100 - (Date.now() - last_geocode_request)
  );

  if (wait) {
    await new Promise(resolve => setTimeout(resolve, wait));
  }

  last_geocode_request = Date.now();

  const params = new URLSearchParams({
    q: term,
    format: "jsonv2",
    limit: "6",
    addressdetails: "1"
  });

  const results = await https_json(
    `https://nominatim.openstreetmap.org/search?${params}`,
    {
      "User-Agent": "AirthingsLocalDashboard/1.0 (personal local weather panel)",
      "Accept-Language": "en"
    }
  );

  const locations = results.map(item => ({
    name: item.display_name,
    latitude: Number(item.lat),
    longitude: Number(item.lon)
  })).filter(item =>
    valid_coordinates(item.latitude, item.longitude)
  );

  geocode_cache.set(cache_key, {
    time: Date.now(),
    results: locations
  });

  return locations;
}

async function get_outdoor_conditions() {
  const location = config.outdoor_location;

  if (!location || !valid_coordinates(
    Number(location.latitude),
    Number(location.longitude)
  )) {
    throw new Error("Outdoor location is not configured.");
  }

  // Cache conditions for 10 minutes.
  if (
    outdoor_cache.data &&
    Date.now() - outdoor_cache.fetched_at < 10 * 60 * 1000
  ) {
    return outdoor_cache.data;
  }

  const latitude = Number(location.latitude);
  const longitude = Number(location.longitude);

  const weather_params = new URLSearchParams({
    latitude: String(latitude),
    longitude: String(longitude),
    current: [
      "temperature_2m",
      "relative_humidity_2m",
      "apparent_temperature",
      "pressure_msl",
      "wind_speed_10m",
      "weather_code"
    ].join(","),
    daily: "sunrise,sunset",
    timezone: "auto"
  });

  const air_params = new URLSearchParams({
    latitude: String(latitude),
    longitude: String(longitude),
    current: "pm2_5,ozone",
    timezone: "auto"
  });

  const [weather, air] = await Promise.all([
    https_json(
      `https://api.open-meteo.com/v1/forecast?${weather_params}`
    ),
    https_json(
      `https://air-quality-api.open-meteo.com/v1/air-quality?${air_params}`
    )
  ]);

    const data = {
    location: {
        name: location.name,
        latitude,
        longitude
    },
    weather: {
        ...(weather.current || {}),
        sunrise: weather.daily?.sunrise?.[0] || null,
        sunset: weather.daily?.sunset?.[0] || null
    },
    weather_units: weather.current_units || {},
    air: air.current || {},
    air_units: air.current_units || {},
    fetched_at: new Date().toISOString(),
    source: "Open-Meteo"
    };

  outdoor_cache = {
    data,
    fetched_at: Date.now()
  };

  return data;
}

function read_devices() {
  try {
    const parsed = JSON.parse(fs.readFileSync(DEVICES_FILE, "utf8"));
    return (parsed.devices || []).map(device => ({
      ...device,
      enabled: device.enabled !== false
    }));
  } catch {
    return [];
  }
}

function save_devices(devices) {
  const temp = `${DEVICES_FILE}.tmp`;
  fs.writeFileSync(temp, JSON.stringify({ devices }, null, 2));
  fs.renameSync(temp, DEVICES_FILE);
}

function send_json(res, status, data) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store"
  });
  res.end(body);
}

function read_body(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", chunk => {
      body += chunk;
      if (body.length > 1_000_000) {
        reject(new Error("Request body too large"));
        req.destroy();
      }
    });
    req.on("end", () => {
      if (!body) return resolve({});
      try {
        resolve(JSON.parse(body));
      } catch {
        reject(new Error("Invalid JSON body"));
      }
    });
    req.on("error", reject);
  });
}

function parse_timestamp_value(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string" && value.trim()) {
    // Support numeric Unix timestamps and ISO date strings.
    const numeric = Number(value);

    if (Number.isFinite(numeric)) {
      return numeric;
    }

    const parsed = Date.parse(value);

    if (Number.isFinite(parsed)) {
      return parsed / 1000;
    }
  }

  return null;
}

function record_timestamp(record) {
  // Always prefer the individual sample timestamp.
  // Do not fall back to block_timestamp: it represents the
  // block, not necessarily the individual sample.
  return (
    parse_timestamp_value(record.timestamp) ??
    parse_timestamp_value(record.timestamp_utc) ??
    parse_timestamp_value(record.time) ??
    parse_timestamp_value(record.time_utc)
  );
}

async function load_device_history(device) {
  const serial = encodeURIComponent(String(device.serial));

  const records = await api_get_all(
    `/api/devices/${serial}/history`
  );

  return records
    .map(record => {
      const timestamp = record_timestamp(record);

      if (timestamp === null) return null;

      return {
        ...record,
        timestamp,
        timestamp_utc:
          record.timestamp_utc ||
          new Date(timestamp * 1000).toISOString(),
        _timestamp: timestamp
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.timestamp - b.timestamp);
}

async function load_device_acp(device) {
  const serial = encodeURIComponent(String(device.serial));

  return api_get_all(
    `/api/devices/${serial}/acp`
  );
}

async function get_device_data(device) {
  const serial = encodeURIComponent(String(device.serial));

  const [history_data, acp_data] = await Promise.all([
    api_get(
      `/api/devices/${serial}/history?limit=1&order=desc`
    ),
    api_get(
      `/api/devices/${serial}/acp?limit=1&order=desc`
    )
  ]);

  const latest = history_data.records?.[0] || null;
  const latest_acp = acp_data.responses?.[0] || null;

  const timestamp = latest
    ? record_timestamp(latest)
    : null;

  return {
    ...device,
    record_count: history_data.total || 0,
    latest: latest
      ? {
          ...latest,
          _timestamp: timestamp
        }
      : null,
    latest_acp,
    last_reading_timestamp: timestamp
  };
}

function get_lookback_hours() {
  return Math.max(
    1,
    Math.ceil(Number(config.history_interval_minutes) / 60) + 1
  );
}

function build_query_args(job) {
  const args = [QUERY_SCRIPT];

  if (job.serial) {
    args.push("--serial", String(job.serial));
  }

  if (job.full) {
    args.push("--full");
  } else {
    args.push("--hours", String(job.hours ?? get_lookback_hours()));
  }

  return args;
}

function enqueue_job(type, options = {}) {
  const job = {
    id: next_job_id++,
    type,
    serial: options.serial || null,
    full: Boolean(options.full),
    hours: options.hours ?? get_lookback_hours(),
    status: "queued",
    created_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
    output: "",
    error: null
  };

  job_queue.push(job);
  process_queue();

  return job;
}

function append_job_output(job, chunk) {
  job.output += chunk.toString();

  if (job.output.length > 30000) {
    job.output = job.output.slice(-30000);
  }
}

function load_device_health_state() {
  try {
    return JSON.parse(
      fs.readFileSync(DEVICE_HEALTH_STATE_FILE, "utf8")
    );
  } catch {
    return {};
  }
}

function save_device_health_state(state) {
  const temp = `${DEVICE_HEALTH_STATE_FILE}.tmp`;

  fs.writeFileSync(
    temp,
    JSON.stringify(state, null, 2)
  );

  fs.renameSync(temp, DEVICE_HEALTH_STATE_FILE);
}

function prune_device_health_history() {
  if (!fs.existsSync(DEVICE_HEALTH_FILE)) {
    return;
  }

  try {
    const cutoff = Date.now() - DEVICE_HEALTH_RETENTION_MS;

    const lines = fs.readFileSync(
      DEVICE_HEALTH_FILE,
      "utf8"
    ).split(/\r?\n/);

    const retained = lines.filter(line => {
      if (!line.trim()) return false;

      try {
        const event = JSON.parse(line);
        const timestamp = Date.parse(event.timestamp);

        // Preserve records with an unrecognizable timestamp
        // rather than accidentally deleting them.
        return !Number.isFinite(timestamp) || timestamp >= cutoff;
      } catch {
        return false;
      }
    });

    fs.writeFileSync(
      DEVICE_HEALTH_FILE,
      retained.length
        ? `${retained.join("\n")}\n`
        : ""
    );
  } catch (error) {
    console.error("Could not prune device health history:", error);
  }
}

function record_device_health_event(job, event) {
  if (
    !event ||
    event.event !== "device_attempt" ||
    !event.serial ||
    typeof event.success !== "boolean"
  ) {
    return;
  }

  const record = {
    ...event,
    job_id: job.id,
    job_type: job.type
  };

  try {
    prune_device_health_history();

    fs.appendFileSync(
      DEVICE_HEALTH_FILE,
      `${JSON.stringify(record)}\n`
    );

    if (record.success) {
      const state = load_device_health_state();
      const serial = String(record.serial);

      state[serial] = {
        device: record.device,
        serial,
        model: record.model,
        model_id: record.model_id,
        last_success: record.timestamp,
        last_success_job_id: job.id
      };

      save_device_health_state(state);
    }
  } catch (error) {
    console.error("Could not save device health event:", error);
  }
}

function process_job_stdout_line(job, line) {
  const prefix = "EVENT_JSON:";

  if (!line.startsWith(prefix)) {
    return;
  }

  try {
    const event = JSON.parse(line.slice(prefix.length));
    record_device_health_event(job, event);
  } catch (error) {
    console.error("Invalid QueryWave JSON event:", error.message);
  }
}

function process_job_stdout(job, chunk) {
  append_job_output(job, chunk);

  job.stdout_buffer += chunk.toString();

  const lines = job.stdout_buffer.split(/\r?\n/);
  job.stdout_buffer = lines.pop() || "";

  for (const line of lines) {
    process_job_stdout_line(job, line);
  }
}

function finish_job_stdout(job) {
  if (job.stdout_buffer) {
    process_job_stdout_line(job, job.stdout_buffer);
    job.stdout_buffer = "";
  }
}

function process_queue() {
  if (
    active_job ||
    shutting_down ||
    job_queue.length === 0
  ) {
    return;
  }

  const job = job_queue.shift();
  active_job = job;

  job.status = "running";
  job.started_at = new Date().toISOString();
  job.stdout_buffer = "";

  const args = build_query_args(job);

  const child = spawn(PYTHON, args, {
    cwd: PROJECT_DIR,
    env: {
        ...process.env,
        PYTHONUNBUFFERED: "1"
    }
  });

  child.stdout.on("data", chunk => {
    process_job_stdout(job, chunk);
  });

  child.stderr.on("data", chunk => {
    append_job_output(job, chunk);
  });

  child.on("error", error => {
    job.error = error.message;
    finish_job(job, 1);
  });

  child.on("close", code => {
    finish_job_stdout(job);
    finish_job(job, code);
  });
}

function finish_job(job, code) {
  if (job.status !== "running") return;

  job.finished_at = new Date().toISOString();
  job.status = code === 0 ? "completed" : "failed";

  if (code !== 0 && !job.error) {
    job.error = `QueryWave.py exited with code ${code}`;
  }

  last_job = { ...job };
  active_job = null;

  const delay =
    Math.max(
      0,
      Number(config.device_connect_delay_seconds) || 0
    ) * 1000;

  setTimeout(process_queue, delay);
}

function schedule_history() {
  if (scheduler_timer) {
    clearInterval(scheduler_timer);
  }

  const interval_ms =
    Math.max(
      5,
      Number(config.history_interval_minutes) || 180
    ) * 60 * 1000;

  next_history_run = Date.now() + interval_ms;

  scheduler_timer = setInterval(() => {
    if (!shutting_down) {
      enqueue_job("scheduled-history");
    }

    next_history_run = Date.now() + interval_ms;
  }, interval_ms);
}

function start_scheduler() {
  schedule_history();

  // Collect once at startup so the dashboard begins
  // populating immediately.
  enqueue_job("startup-history");
}

function get_status() {
  return {
    running: Boolean(active_job),

    active_job: active_job
      ? {
          id: active_job.id,
          type: active_job.type,
          serial: active_job.serial,
          started_at: active_job.started_at
        }
      : null,

    queued_jobs: job_queue.length,

    next_history_run: next_history_run
      ? new Date(next_history_run).toISOString()
      : null,

    history_interval_minutes:
      config.history_interval_minutes,

    history_lookback_hours:
      get_lookback_hours(),

    last_job: last_job
      ? {
          id: last_job.id,
          type: last_job.type,
          status: last_job.status,
          finished_at: last_job.finished_at,
          error: last_job.error
        }
      : null
  };
}

function metric_value(record, metric) {
  if (!record) return null;

  if (metric === "voc") {
    return record.voc ?? record.voc_ppb ?? null;
  }

  if (metric === "voc_ppb") {
    return record.voc_ppb ?? record.voc ?? null;
  }

  const value = record[metric];

  return typeof value === "number" &&
    Number.isFinite(value)
    ? value
    : null;
}

async function get_comparison(serials, metric, hours) {
  const cutoff = hours > 0
    ? Date.now() / 1000 - hours * 3600
    : 0;

  const devices = read_devices().filter(device =>
    serials.includes(String(device.serial))
  );

  return Promise.all(devices.map(async device => {
    const start = cutoff > 0
      ? new Date(cutoff * 1000).toISOString()
      : null;

    const endpoint = start
      ? `/api/devices/${encodeURIComponent(String(device.serial))}/history?start=${encodeURIComponent(start)}`
      : `/api/devices/${encodeURIComponent(String(device.serial))}/history`;

    const records = await api_get_all(endpoint);

    const points = records
      .map(record => ({
        timestamp: record_timestamp(record),
        y: metric_value(record, metric)
      }))
      .filter(point =>
        point.timestamp !== null &&
        point.timestamp >= cutoff &&
        point.y !== null
      )
      .map(point => ({
        x: point.timestamp * 1000,
        y: point.y
      }));

    return {
      serial: device.serial,
      name: device.name || device.model,
      model: device.model,
      points
    };
  }));
}

async function handle_api(req, res, url) {
  const pathname = url.pathname;

  // ----------------------------------------------
  // Outdoor location search
  // ----------------------------------------------

  if (
    req.method === "GET" &&
    pathname === "/api/outdoor/search"
  ) {
    const results = await search_outdoor_location(
      url.searchParams.get("q")
    );

    return send_json(res, 200, { results });
  }

  // ----------------------------------------------
  // Outdoor location settings
  // ----------------------------------------------

  if (
    req.method === "POST" &&
    pathname === "/api/outdoor/location"
  ) {
    const body = await read_body(req);

    const latitude = Number(body.latitude);
    const longitude = Number(body.longitude);
    const name = String(body.name || "").trim();

    if (
      !valid_coordinates(latitude, longitude) ||
      !name ||
      name.length > 300
    ) {
      return send_json(res, 400, {
        error: "Invalid location."
      });
    }

    config.outdoor_location = {
      name,
      latitude,
      longitude
    };

    save_config();

    // Force a fresh reading for the new location.
    outdoor_cache = {
      data: null,
      fetched_at: 0
    };

    return send_json(res, 200, {
      ok: true,
      location: config.outdoor_location
    });
  }

  // ----------------------------------------------
  // Outdoor conditions
  // ----------------------------------------------

  if (
    req.method === "GET" &&
    pathname === "/api/outdoor"
  ) {
    const data = await get_outdoor_conditions();
    return send_json(res, 200, data);
  }

  // ----------------------------------------------
  // Devices
  // ----------------------------------------------

  if (req.method === "GET" && url.pathname === "/api/devices") {
    const devices = read_devices();
    const result = await Promise.all(
      devices.map(device => get_device_data(device))
    );

    return send_json(res, 200, result);
  }

  if (req.method === "GET" && url.pathname === "/api/data") {
    const devices = read_devices();
    const result = await Promise.all(
      devices.map(device => get_device_data(device))
    );

    return send_json(res, 200, {
      generated_at: new Date().toISOString(),
      devices: result
    });
  }

  // ----------------------------------------------
  // Device health history
  // ----------------------------------------------

  if (
    req.method === "GET" &&
    pathname === "/api/device-health"
  ) {
    let events = [];

    try {
      if (fs.existsSync(DEVICE_HEALTH_FILE)) {
        events = fs.readFileSync(
          DEVICE_HEALTH_FILE,
          "utf8"
        )
          .split(/\r?\n/)
          .filter(Boolean)
          .map(line => JSON.parse(line));
      }
    } catch (error) {
      console.error("Could not read device health history:", error);
    }

    return send_json(res, 200, {
      retention_days: DEVICE_HEALTH_RETENTION_DAYS,
      events,
      devices: load_device_health_state()
    });
  }

  // ----------------------------------------------
  // Collector status and jobs
  // ----------------------------------------------

  if (
    req.method === "GET" &&
    pathname === "/api/status"
  ) {
    return send_json(res, 200, get_status());
  }

  if (
    req.method === "GET" &&
    pathname === "/api/jobs"
  ) {
    return send_json(res, 200, {
      active: active_job,
      queued: job_queue,
      last: last_job
    });
  }

  // ----------------------------------------------
  // Configuration
  // ----------------------------------------------

  if (
    req.method === "GET" &&
    pathname === "/api/config"
  ) {
    return send_json(res, 200, {
      history_interval_minutes:
        config.history_interval_minutes,

      history_lookback_hours:
        get_lookback_hours(),

      device_connect_delay_seconds:
        config.device_connect_delay_seconds,

      outdoor_location: config.outdoor_location
    });
  }

  if (
    req.method === "POST" &&
    pathname === "/api/config"
  ) {
    const body = await read_body(req);

    if (body.history_interval_minutes !== undefined) {
      const interval = Number(
        body.history_interval_minutes
      );

      if (
        !Number.isFinite(interval) ||
        interval < 5 ||
        interval > 10080
      ) {
        return send_json(res, 400, {
          error:
            "Polling interval must be between 5 minutes and 7 days."
        });
      }

      config.history_interval_minutes = interval;
    }

    if (body.device_connect_delay_seconds !== undefined) {
      const delay = Number(
        body.device_connect_delay_seconds
      );

      if (
        !Number.isFinite(delay) ||
        delay < 0 ||
        delay > 120
      ) {
        return send_json(res, 400, {
          error:
            "Device connection delay must be between 0 and 120 seconds."
        });
      }

      config.device_connect_delay_seconds = delay;
    }

    save_config();
    schedule_history();

    return send_json(res, 200, {
      ok: true,

      history_interval_minutes:
        config.history_interval_minutes,

      history_lookback_hours:
        get_lookback_hours(),

      device_connect_delay_seconds:
        config.device_connect_delay_seconds
    });
  }

  // ----------------------------------------------
  // Comparisons
  // ----------------------------------------------

  if (
    req.method === "GET" &&
    pathname === "/api/compare"
  ) {
    const serials = (
      url.searchParams.get("serials") || ""
    ).split(",").filter(Boolean);

    const metric =
      url.searchParams.get("metric") ||
      "temperature_c";

    const range =
      url.searchParams.get("hours") || "24";

    const hours = range === "all"
      ? 0
      : Math.max(1, Number(range) || 24);

    return send_json(res, 200, {
      metric,
      hours: range === "all" ? null : hours,
      series: await get_comparison(serials, metric, hours)
    });
  }

  // ----------------------------------------------
  // Individual device history
  // ----------------------------------------------

  const device_match = pathname.match(
    /^\/api\/device\/([^/]+)$/
  );

  if (device_match && req.method === "GET") {
    const serial = decodeURIComponent(device_match[1]);

    const device = read_devices().find(
      item => String(item.serial) === serial
    );

    if (!device) {
      return send_json(res, 404, {
        error: "Device not found"
      });
    }

    const start = url.searchParams.get("start");
    const end = url.searchParams.get("end");

    const history_endpoint =
      `/api/devices/${encodeURIComponent(serial)}/history`;

    const params = new URLSearchParams();

    if (start) params.set("start", start);
    if (end) params.set("end", end);

    const history_url = params.toString()
      ? `${history_endpoint}?${params.toString()}`
      : history_endpoint;

    const [device_data, history, acp] = await Promise.all([
      get_device_data(device),
      api_get_all(history_url),
      load_device_acp(device)
    ]);

    return send_json(res, 200, {
      device: device_data,
      history,
      acp
    });
  }


  // ----------------------------------------------
  // Device management
  // ----------------------------------------------

  const patch_match = pathname.match(
    /^\/api\/device\/([^/]+)$/
  );

  if (patch_match && req.method === "PATCH") {
    const serial = decodeURIComponent(patch_match[1]);
    const body = await read_body(req);
    const devices = read_devices();

    const device = devices.find(
      item => String(item.serial) === serial
    );

    if (!device) {
      return send_json(res, 404, {
        error: "Device not found"
      });
    }

    if (body.name !== undefined) {
      const name = String(body.name).trim();

      if (!name || name.length > 60) {
        return send_json(res, 400, {
          error: "Name must be 1–60 characters."
        });
      }

      device.name = name;
    }

    if (body.enabled !== undefined) {
      device.enabled = Boolean(body.enabled);
    }

    save_devices(devices);

    return send_json(res, 200, {
      ok: true,
      device
    });
  }

  // ----------------------------------------------
  // Manual collection
  // ----------------------------------------------

  if (
    req.method === "POST" &&
    pathname === "/api/query"
  ) {
    const job = enqueue_job("manual-history");

    return send_json(res, 202, {
      ok: true,
      job
    });
  }

  if (
    req.method === "POST" &&
    pathname === "/api/query/full"
  ) {
    const job = enqueue_job(
      "manual-full-history",
      { full: true }
    );

    return send_json(res, 202, {
      ok: true,
      job
    });
  }

  const query_device_match = pathname.match(
    /^\/api\/query\/([^/]+)$/
  );

  if (req.method === "POST" && query_device_match) {
    const serial = decodeURIComponent(
      query_device_match[1]
    );

    if (
      !read_devices().some(
        device => String(device.serial) === serial
      )
    ) {
      return send_json(res, 404, {
        error: "Device not found"
      });
    }

    const job = enqueue_job(
      "manual-device-history",
      { serial }
    );

    return send_json(res, 202, {
      ok: true,
      job
    });
  }

  const full_device_match = pathname.match(
    /^\/api\/query\/full\/([^/]+)$/
  );

  if (
    req.method === "POST" &&
    full_device_match
  ) {
    const serial = decodeURIComponent(
      full_device_match[1]
    );

    if (
      !read_devices().some(
        device => String(device.serial) === serial
      )
    ) {
      return send_json(res, 404, {
        error: "Device not found"
      });
    }

    const job = enqueue_job(
      "manual-device-full-history",
      {
        serial,
        full: true
      }
    );

    return send_json(res, 202, {
      ok: true,
      job
    });
  }

  return send_json(res, 404, {
    error: "API endpoint not found"
  });
}

// --------------------------------------------------
// Static files
// --------------------------------------------------

function content_type(file) {
  const ext = path.extname(file).toLowerCase();

  return ({
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon"
  })[ext] || "application/octet-stream";
}

function serve_static(req, res, url) {
  const requested = url.pathname === "/"
    ? "/index.html"
    : decodeURIComponent(url.pathname);

  const file = path.resolve(
    PUBLIC_DIR,
    `.${requested}`
  );

  if (
    !file.startsWith(`${PUBLIC_DIR}${path.sep}`) &&
    file !== path.join(PUBLIC_DIR, "index.html")
  ) {
    res.writeHead(403);
    return res.end("Forbidden");
  }

  fs.readFile(file, (error, data) => {
    if (error) {
      res.writeHead(404);
      return res.end("Not found");
    }

    res.writeHead(200, {
      "Content-Type": content_type(file),
      "Cache-Control": "no-cache"
    });

    res.end(data);
  });
}

// --------------------------------------------------
// HTTP server
// --------------------------------------------------

const server = http.createServer(
  async (req, res) => {
    let url;

    try {
      url = new URL(
        req.url,
        `http://${req.headers.host || "localhost"}`
      );
    } catch {
      return send_json(res, 400, {
        error: "Invalid URL"
      });
    }

    if (url.pathname.startsWith("/api/")) {
      try {
        await handle_api(req, res, url);
      } catch (error) {
        console.error("API error:", error);

        if (!res.headersSent) {
          send_json(res, 500, {
            error: error.message
          });
        }
      }

      return;
    }

    serve_static(req, res, url);
  }
);

const PORT = Number(config.port) || 3000;

prune_device_health_history();

server.listen(PORT, () => {
  console.log(
    `Airthings Dashboard V3 running at http://localhost:${PORT}`
  );

  start_scheduler();
});

// --------------------------------------------------
// Shutdown
// --------------------------------------------------

function shutdown() {
  if (shutting_down) return;

  shutting_down = true;

  if (scheduler_timer) {
    clearInterval(scheduler_timer);
  }

  server.close(() => process.exit(0));

  setTimeout(
    () => process.exit(0),
    3000
  ).unref();
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
