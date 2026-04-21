module.exports = {
  apps : [{
    name: "btc-sniper",
    script: "btc_sniper/main.py",
    interpreter: "/root/berkah_jaya/btc_sniper/venv/bin/python3",
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: "1G",
    env: {
      NODE_ENV: "production",
      PYTHONUNBUFFERED: "1",
      PYTHONPATH: "./btc_sniper",
      LOG_LEVEL: "INFO"
    },
    error_file: "./output/pm2-error.log",
    out_file: "./output/pm2-out.log",
    log_date_format: "YYYY-MM-DD HH:mm:ss",
    merge_logs: true
  }]
}
