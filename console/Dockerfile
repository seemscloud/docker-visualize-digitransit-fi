FROM vectorized/console:latest

ENV PATH="/app:${PATH}"

COPY ./entrypoint.sh .

ENTRYPOINT ["/bin/sh", "entrypoint.sh"]