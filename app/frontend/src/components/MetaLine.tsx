// "10 film · taslak · onay bekliyor" gibi ayraçlı satır. Ayraçlar parçaların SOLUNDA (CSS ::before) çizilir ve kap
// sola kaydırılıp kırpılır; satır kırılınca her satırın ilk parçasının ayracı kırpılır, yani ayraç yalnız aynı satırdaki
// iki parça arasında görünür. Ayraç süstür, ekran okuyucuya parçalar art arda okunur.
export function MetaLine({ parts }: { parts: string[] }) {
  return (
    <span className="label metaline">
      <span className="metaline-in">
        {parts.map((part) => (
          <span key={part}>{part}</span>
        ))}
      </span>
    </span>
  )
}
