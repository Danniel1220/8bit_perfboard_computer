"""Deterministic minimum spanning guides between disconnected net sections.

These are endpoint-to-endpoint indications, never proposed physical wire paths.
"""
def guides(router):
    result=[];w=router.g.w
    for net in sorted(router.g.terminals):
        sections=router.components(net)
        if len(sections)<2:continue
        # Frontier/end nodes reduce work without inventing endpoints in an IC.
        graph=router.graphs.get(net,{})
        ends=[]
        for section in sections:
            available=set(section)-router.g.blocked-router.g.pins-router.g.no_turn
            frontier={p for p in available if len(graph.get(p,()))<=1}
            ends.append(sorted(frontier or available or section))
        joined={0}
        while len(joined)<len(ends):
            choice=None
            for i in sorted(joined):
                for j in range(len(ends)):
                    if j in joined:continue
                    for a in ends[i]:
                        for b in ends[j]:
                            item=(abs(a%w-b%w)+abs(a//w-b//w),a,b,j)
                            if choice is None or item<choice:choice=item
            if choice is None:break
            distance,a,b,j=choice;joined.add(j)
            result.append({'net':net,'a':a,'b':b,'distance':distance,'kind':'guide-not-route'})
    return result
