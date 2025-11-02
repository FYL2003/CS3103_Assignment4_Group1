# Quick Start: Using the Split Branches

## Current Status

✅ **2 branches created and ready to push:**
1. `fix-deprecated-datetime-utcnow`
2. `move-channelmetrics-to-api`

📋 **Existing placeholder branches (need updating or replacing):**
1. `move-metrics-to-API`
2. `abstract-cert-generation-to-api`
3. `fix-PDR-calculation`
4. `implement-retransmission-timeout`

## Quick Commands

### To Push New Branches:

```bash
cd /path/to/repo

# Push the datetime fix branch
git push origin fix-deprecated-datetime-utcnow

# Push the ChannelMetrics branch
git push origin move-channelmetrics-to-api
```

### To Create PRs on GitHub:

After pushing, go to:
- https://github.com/FYL2003/CS3103_Assignment4_Group1/pulls
- Click "New pull request"
- Select your branch
- Add description from the commit message

### To View Branch Changes Locally:

```bash
# View datetime fix changes
git checkout fix-deprecated-datetime-utcnow
git diff main

# View ChannelMetrics changes
git checkout move-channelmetrics-to-api
git diff main
```

### To Replace Placeholder Branches:

If you want to update the existing placeholder branches with real content:

```bash
# Example: Update move-metrics-to-API with real changes
git checkout move-metrics-to-API
git reset --hard main
git cherry-pick move-channelmetrics-to-api
git push -f origin move-metrics-to-API

# Then create PR from move-metrics-to-API branch
```

## Verification Commands

### Test datetime fix:
```bash
git checkout fix-deprecated-datetime-utcnow
python3 -m py_compile generate_cert.py
python3 generate_cert.py --force  # Should work without warnings
```

### Test ChannelMetrics:
```bash
git checkout move-channelmetrics-to-api
python3 -m py_compile GameNetAPI.py

# Quick test
python3 -c "from GameNetAPI import ChannelMetrics; m = ChannelMetrics(); m.add_rtt(50.0); print(f'Avg RTT: {m.avg_rtt}ms')"
```

## File Locations

- **`PR_SPLIT_GUIDE.md`** → Full technical guide with all branch details
- **`SPLITTING_SUMMARY.md`** → Overview and next steps
- **`QUICK_START.md`** → This file (quick commands)

## Branch Details Summary

| Branch | Status | Files | Lines | Purpose |
|--------|--------|-------|-------|---------|
| fix-deprecated-datetime-utcnow | ✅ Created | 2 | +9, -8 | Fix Python 3.12+ deprecation |
| move-channelmetrics-to-api | ✅ Created | 1 | +143 | Add metrics class to API |
| add-connection-termination-callback | 📋 Planned | 2 | ~50 | Connection event handling |
| add-track-packet-metrics | 📋 Planned | 1 | ~80 | Metrics tracking method |
| implement-timeout-and-buffering | 📋 Planned | 1 | ~90 | Timeout/buffering logic |
| add-statistics-methods | 📋 Planned | 1 | ~160 | Stats collection/display |
| update-server-use-api-metrics | 📋 Planned | 1 | ~200 | Server refactoring |
| add-documentation | 📋 Planned | 4 | ~780 | Documentation files |

## Recommended Workflow

### Phase 1: Push and Review First 2 Branches
```bash
# 1. Push branches
git push origin fix-deprecated-datetime-utcnow
git push origin move-channelmetrics-to-api

# 2. Create PRs on GitHub
# 3. Review and merge these 2 PRs
```

### Phase 2: Create Remaining Branches
Follow `PR_SPLIT_GUIDE.md` to create branches 3-8:
- Each branch should start from `main`
- Make focused changes per branch
- Test independently
- Create PR when ready

### Phase 3: Incremental Merging
Merge in recommended order:
1. fix-deprecated-datetime-utcnow (no deps)
2. move-channelmetrics-to-api (no deps)
3. add-connection-termination-callback
4. add-track-packet-metrics (depends on 2)
5. implement-timeout-and-buffering (parallel with 4)
6. add-statistics-methods (depends on 2, 4)
7. update-server-use-api-metrics (depends on 2, 4, 6)
8. add-documentation (anytime)

## Help

- **Detailed guide:** See `PR_SPLIT_GUIDE.md`
- **Overview:** See `SPLITTING_SUMMARY.md`
- **Original PR:** https://github.com/FYL2003/CS3103_Assignment4_Group1/pull/5

## Success Criteria

✅ Branch pushed to GitHub
✅ PR created
✅ Tests passing
✅ Code review completed
✅ Merged to main

Repeat for each branch!
