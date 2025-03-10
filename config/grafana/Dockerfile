FROM grafana/grafana

COPY ./grafana_datasource.yml /etc/grafana/provisioning/datasources/datasource.yml
COPY ./grafana_dashboard_config.yml /etc/grafana/provisioning/dashboards/dashboard.yml
COPY ./grafana_dashboard.v2.json /etc/grafana/provisioning/dashboards/grafana_dashboard.v2.json
COPY ./grafana.ini /etc/grafana/grafana.ini