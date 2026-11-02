# CI/CD: SSH'siz tarqatish

2026-yil noyabrdan jamoada serverlarga SSH yo'q. Hamma ish GitLab orqali:
push sinovlarni ishga tushiradi, `deploy` tugmasi prod'ga chiqaradi,
`rollback` tugmasi orqaga qaytaradi.

| Qism | Qayerda | Nima qiladi |
|---|---|---|
| `.gitlab-ci.yml` | repo ildizi | `api-tests`, `web-build`, keyin `main` da `deploy` / `rollback` |
| `deploy/ci-deploy.sh` | repo | prod daraxtini ff-merge, API restart, web obraz (o'zgargan bo'lsa), health |
| `deploy/gitlab-runner.user.service` | prod hostda user unit | runner'ning o'zi |
| GitLab Runner | prod host (10.10.50.8), shell executor, tag `venera-prod` | ishlarni shu hostda, `~/Venera` egasi nomidan bajaradi |

Backend avvalgidek host'da venv bilan, user unit sifatida ishlaydi
(`docs/deploy-api.md`); frontend avvalgidek podman konteynerida. CI faqat
qo'lda qilinadigan `git pull` + `restart` + `podman build` qadamlarini
bajaradi, boshqa hech narsa o'zgarmaydi.

## Bir marta: runner'ni yoqish (prod hostda, ~/Venera egasi nomidan)

Runner `~/.gitlab-runner/config.toml` da allaqachon ro'yxatdan o'tgan
("brb-deploy (user=ymamajonov)", GitLab uni "is valid" deb tasdiqlaydi).
Faqat xizmat sifatida ishga tushirish qolgan:

```bash
mkdir -p ~/.config/systemd/user ~/gitlab-runner-builds
cp ~/Venera/deploy/gitlab-runner.user.service ~/.config/systemd/user/gitlab-runner.service
systemctl --user daemon-reload
systemctl --user enable --now gitlab-runner
systemctl --user status gitlab-runner --no-pager
```

GitLab tomonida (Settings → CI/CD → Runners) shu runner'ga `venera-prod` tegi
qo'yilgan bo'lishi kerak, aks holda `.gitlab-ci.yml` dagi `tags` o'zgartiriladi.

## Kundalik ish

1. Branch'ga push: `api-tests` (pytest, `test_docs.py` dan tashqari, u Swagger
   statik fayllarini prod daraxtidan kutadi) va `web-build` (`npm run build`).
2. MR `main` ga qo'shilgach: sinovlar yana, keyin `deploy` tugmasi. Deploy
   nima qiladi:
   - prod HEAD ni `pre-ci-<vaqt>` tegi bilan belgilaydi (rollback nuqtasi);
   - `git merge --ff-only <commit>`;
   - `apps/api/pyproject.toml` o'zgargan bo'lsa `pip install -e`;
   - `systemctl --user restart venera-api`, `/api/health` ni 40 s kutadi;
   - `apps/web/` o'zgargan bo'lsa `podman build` + sana-sha tegi +
     `systemctl --user restart venera-frontend`, `/healthz` ni 60 s kutadi.
   Bir vaqtda faqat bitta deploy yoki rollback ishlaydi (`resource_group`).
3. Noto'g'ri chiqsa: `rollback` tugmasi. Oxirgi `pre-ci-*` tegiga qaytadi,
   API restart, shu commit uchun yig'ilgan frontend obrazini `latest` qiladi
   (yo'q bo'lsa qayta yig'adi).
4. Frontend'ni majburan qayta yig'ish: `deploy` ishiga `FORCE_WEB=1`
   o'zgaruvchisi bilan.

## Qo'lda qoladiganlar

- `apps/api/.env`, `config/users.yaml` va `~/.local/share/venera-tg*` dagi
  fayllar host'da turadi, git'da emas; ularni o'zgartirish uchun hozircha
  host'ga kirish kerak (keyingi qadam: CI File o'zgaruvchilari).
- Runner'ning o'zi (yuqoridagi 5 qator) va linger - bir marta.
