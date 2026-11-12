const LABELS = [
  {x:.24,words:["Expert","tags"],color:"purple"},
  {x:.50,words:["Overlap"],color:"green"},
  {x:.76,words:["Agent","detections"],color:"darkred"},
];

export function laneHeaderLayout(laneWidth, measure) {
  // Leave a visible gap between adjacent headers. Very narrow tracks wrap
  // long words as well; extra top margin keeps every line inside the figure.
  const maxWidth = Math.max(8,Number(laneWidth || 0)*.26-8);
  let size = 12;
  while (size>9 && LABELS.some(label=>label.words.some(word=>measure(word,size)>maxWidth))) size--;
  function wrap(word) {
    const lines=[];let current="";
    for (const letter of word) {
      if (current && measure(current+letter,size)>maxWidth) { lines.push(current);current=""; }
      current+=letter;
    }
    if (current) lines.push(current);
    return lines;
  }
  let maxLines=1;
  const annotations=LABELS.map(label=>{
    const lines=label.words.flatMap(wrap);maxLines=Math.max(maxLines,lines.length);
    return {xref:"x4",yref:"paper",x:label.x,y:1,xanchor:"center",yanchor:"bottom",yshift:6,
      text:"<b>"+lines.join("<br>")+"</b>",showarrow:false,align:"center",borderpad:0,
      font:{family:"Arial, sans-serif",color:label.color,size}};
  });
  return {annotations,top:Math.max(45,Math.ceil(size*1.35*maxLines+14))};
}
